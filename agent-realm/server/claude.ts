import Anthropic from '@anthropic-ai/sdk';
import type { z } from 'zod';

export type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max';

export interface CallOptions {
  model: string;
  system: string;
  prompt: string;
  effort?: Effort;
  maxTokens?: number;
  signal?: AbortSignal;
  /** Called with each streamed text delta. */
  onText?: (delta: string) => void;
  /** JSON schema for structured output (additionalProperties:false + required on every object). */
  schema?: Record<string, unknown>;
}

export interface CallResult {
  text: string;
  tokensIn: number;
  tokensOut: number;
  model: string;
}

export class ClaudeError extends Error {
  constructor(
    message: string,
    readonly retryable = false,
  ) {
    super(message);
    this.name = 'ClaudeError';
  }
}

let client: Anthropic | undefined;
function getClient(): Anthropic {
  client ??= new Anthropic({ maxRetries: 3 });
  return client;
}

/** Haiku 4.5 predates adaptive thinking and effort. */
function supportsAdaptive(model: string): boolean {
  return !/haiku-4|claude-3|sonnet-4-5|opus-4-5|opus-4-1|opus-4-0|sonnet-4-0/.test(model);
}

/** Turn SDK errors into readable, non-sensitive messages. */
export function describeError(err: unknown): ClaudeError {
  if (err instanceof ClaudeError) return err;
  if (err instanceof Anthropic.APIUserAbortError) return new ClaudeError('Request cancelled');
  if (err instanceof Anthropic.AuthenticationError) return new ClaudeError('Claude API rejected the credentials (401) — check ANTHROPIC_API_KEY');
  if (err instanceof Anthropic.PermissionDeniedError) return new ClaudeError('Claude API permission denied (403) for this model or key');
  if (err instanceof Anthropic.NotFoundError) return new ClaudeError('Model not found (404) — check realm.config.json model ids');
  if (err instanceof Anthropic.RateLimitError) return new ClaudeError('Rate limited by the Claude API (429) — try again shortly', true);
  if (err instanceof Anthropic.BadRequestError) return new ClaudeError(`Claude API rejected the request (400): ${err.message.slice(0, 200)}`);
  if (err instanceof Anthropic.InternalServerError) return new ClaudeError(`Claude API server error (${err.status}) — try again`, true);
  if (err instanceof Anthropic.APIConnectionError) return new ClaudeError('Could not reach the Claude API (network error)', true);
  if (err instanceof Anthropic.APIError) return new ClaudeError(`Claude API error ${err.status ?? ''}: ${err.message.slice(0, 200)}`);
  return new ClaudeError(err instanceof Error ? err.message : String(err));
}

export async function callClaude(opts: CallOptions): Promise<CallResult> {
  const adaptive = supportsAdaptive(opts.model);
  const outputConfig: Anthropic.Beta.Messages.BetaOutputConfig = {};
  if (adaptive && opts.effort) outputConfig.effort = opts.effort;
  if (opts.schema) outputConfig.format = { type: 'json_schema', schema: opts.schema };

  try {
    const stream = getClient().beta.messages.stream(
      {
        model: opts.model,
        max_tokens: opts.maxTokens ?? (adaptive ? 32000 : 16000),
        // Server-side refusal fallbacks for the Fable/Opus tier.
        ...(/fable|opus|mythos/.test(opts.model) ? { betas: ['server-side-fallback-2026-07-01'], fallbacks: 'default' as const } : {}),
        ...(adaptive ? { thinking: { type: 'adaptive' as const } } : {}),
        ...(Object.keys(outputConfig).length ? { output_config: outputConfig } : {}),
        system: opts.system,
        messages: [{ role: 'user', content: opts.prompt }],
      },
      { signal: opts.signal },
    );
    if (opts.onText) stream.on('text', (delta) => opts.onText?.(delta));
    const message = await stream.finalMessage();

    if (message.stop_reason === 'refusal') {
      const category = message.stop_details?.category;
      throw new ClaudeError(`The model declined this request${category ? ` (${category})` : ''}`);
    }
    const text = message.content
      .filter((b): b is Anthropic.Beta.Messages.BetaTextBlock => b.type === 'text')
      .map((b) => b.text)
      .join('');
    if (message.stop_reason === 'max_tokens' && !text) throw new ClaudeError('The model ran out of output tokens before answering');
    return {
      text,
      tokensIn: (message.usage.input_tokens ?? 0) + (message.usage.cache_read_input_tokens ?? 0) + (message.usage.cache_creation_input_tokens ?? 0),
      tokensOut: message.usage.output_tokens ?? 0,
      model: message.model,
    };
  } catch (err) {
    throw describeError(err);
  }
}

/** Structured-output call: JSON schema constrains the model, zod validates the result. */
export async function callClaudeJson<T>(opts: CallOptions & { schema: Record<string, unknown> }, validator: z.ZodType<T>): Promise<CallResult & { data: T }> {
  const result = await callClaude(opts);
  let parsed: unknown;
  try {
    parsed = JSON.parse(result.text);
  } catch {
    throw new ClaudeError('The model returned malformed JSON for a structured response');
  }
  const check = validator.safeParse(parsed);
  if (!check.success) throw new ClaudeError(`Structured response failed validation: ${check.error.issues[0]?.message ?? 'invalid'}`);
  return { ...result, data: check.data };
}
