// The "brain" is what council members and workers think with. The council state machine is
// identical for real missions (ApiBrain → Claude API) and simulated ones (SimBrain, simulation.ts).
import { z } from 'zod';
import type { AgentSource, AgentStatus, MissionFramework, TaskPriority } from '../shared/protocol.ts';
import { callClaude, callClaudeJson } from './claude.ts';
import { truncate } from './util.ts';

export interface Gen {
  text: string;
  tokensIn: number;
  tokensOut: number;
}

export interface BrainCall {
  model: string;
  signal: AbortSignal;
  onText: (delta: string) => void;
}

export interface RosterEntry {
  id: string;
  name: string;
  model?: string;
  source: AgentSource;
  controllable: boolean;
  status: AgentStatus;
}

export interface PlanTask {
  key: string;
  title: string;
  goal: string;
  instructions: string;
  acceptance: string[];
  dependsOn: string[];
  priority: TaskPriority;
  suggestedAssignee: string;
}

export interface Plan {
  summary: string;
  framework: MissionFramework;
  tasks: PlanTask[];
}

export interface ProposeInput {
  goal: string;
  seatTitle: string;
  memberName: string;
}

export interface SynthesizeInput {
  goal: string;
  proposals: Array<{ seatTitle: string; memberName: string; text: string }>;
  roster: RosterEntry[];
}

export interface ExecuteInput {
  goal: string;
  summary: string;
  framework?: MissionFramework;
  task: { title: string; goal: string; instructions: string; acceptance: string[] };
  dependencies: Array<{ title: string; output: string }>;
  reviseNotes?: string;
  workerName: string;
}

export interface ReviewInput {
  goal: string;
  task: { title: string; goal: string; acceptance: string[] };
  output: string;
  attempt: number;
}

export interface VerdictInput {
  goal: string;
  summary: string;
  tasks: Array<{ title: string; status: string; notes?: string }>;
}

export interface Review {
  verdict: 'approved' | 'revise';
  notes: string;
}

export interface Brain {
  readonly simulated: boolean;
  /** Rough expected deliverable length, for worker progress bars. */
  expectedChars(input: ExecuteInput): number;
  propose(call: BrainCall, input: ProposeInput): Promise<Gen>;
  synthesize(call: BrainCall, input: SynthesizeInput): Promise<Gen & { plan: Plan }>;
  execute(call: BrainCall, input: ExecuteInput): Promise<Gen>;
  review(call: BrainCall, input: ReviewInput): Promise<Gen & Review>;
  verdict(call: BrainCall, input: VerdictInput): Promise<Gen>;
}

// ── schemas ───────────────────────────────────────────────────────────────

const priorityEnum = z.enum(['low', 'normal', 'high', 'critical']);

export const planValidator = z.object({
  summary: z.string().min(1),
  framework: z.object({
    architecture: z.string(),
    principles: z.array(z.string()),
    milestones: z.array(z.string()),
  }),
  tasks: z
    .array(
      z.object({
        key: z.string().min(1),
        title: z.string().min(1),
        goal: z.string(),
        instructions: z.string().min(1),
        acceptance: z.array(z.string()),
        dependsOn: z.array(z.string()),
        priority: priorityEnum,
        suggestedAssignee: z.string(),
      }),
    )
    .min(1),
});

const reviewValidator = z.object({ verdict: z.enum(['approved', 'revise']), notes: z.string() });

const stringArray = { type: 'array', items: { type: 'string' } } as const;

export const PLAN_JSON_SCHEMA: Record<string, unknown> = {
  type: 'object',
  additionalProperties: false,
  required: ['summary', 'framework', 'tasks'],
  properties: {
    summary: { type: 'string', description: 'Two to four sentence summary of the plan.' },
    framework: {
      type: 'object',
      additionalProperties: false,
      required: ['architecture', 'principles', 'milestones'],
      properties: {
        architecture: { type: 'string', description: 'The shape of the solution, in markdown.' },
        principles: stringArray,
        milestones: stringArray,
      },
    },
    tasks: {
      type: 'array',
      description: 'Between 3 and 8 tasks.',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['key', 'title', 'goal', 'instructions', 'acceptance', 'dependsOn', 'priority', 'suggestedAssignee'],
        properties: {
          key: { type: 'string', description: 'Short unique key, e.g. "t1".' },
          title: { type: 'string' },
          goal: { type: 'string' },
          instructions: { type: 'string', description: 'Detailed, self-contained brief a worker model can execute alone.' },
          acceptance: stringArray,
          dependsOn: { ...stringArray, description: 'Keys of tasks that must finish first.' },
          priority: { type: 'string', enum: ['low', 'normal', 'high', 'critical'] },
          suggestedAssignee: { type: 'string', description: 'Worker id from the roster.' },
        },
      },
    },
  },
};

const REVIEW_JSON_SCHEMA: Record<string, unknown> = {
  type: 'object',
  additionalProperties: false,
  required: ['verdict', 'notes'],
  properties: {
    verdict: { type: 'string', enum: ['approved', 'revise'] },
    notes: { type: 'string', description: 'Concrete, actionable feedback; brief when approved.' },
  },
};

// ── prompts ───────────────────────────────────────────────────────────────

const COUNCIL_SYSTEM = `You sit on the council of Agent Realm, a small team of AI models that plans work and delegates it to worker models.
Workers are language models without filesystem, network or tool access: they can only produce written deliverables (designs, code in fenced blocks, documents, checklists).
Be concrete and decisive. Prefer plans a small crew can finish in a handful of tasks.`;

const WORKER_SYSTEM = `You are a worker in Agent Realm. You receive one task brief from the council and produce the deliverable in markdown.
You cannot run code, browse, or touch files: write the deliverable itself (code in fenced blocks with file paths as headings, designs, docs).
Start with a one-line summary, then use "##" headings for each part. Meet every acceptance criterion explicitly.`;

const SEAT_FOCUS: Record<string, string> = {
  'High Architect': 'the overall architecture and the cleanest decomposition of the work',
  'Grand Strategist': 'sequencing, trade-offs, and the fastest credible path to a useful result',
  Warden: 'risks, failure modes, verification and what "done" must mean',
};

const DEP_CAP = 12_000;

export function executePrompt(input: ExecuteInput): string {
  const parts = [
    `# Mission goal\n${input.goal}`,
    `# Plan summary\n${input.summary}`,
  ];
  if (input.framework) {
    parts.push(
      `# Framework\n${input.framework.architecture}\n\nPrinciples:\n${input.framework.principles.map((p) => `- ${p}`).join('\n')}`,
    );
  }
  for (const dep of input.dependencies) parts.push(`# Output of dependency: ${dep.title}\n${truncate(dep.output, DEP_CAP)}`);
  parts.push(`# Your task: ${input.task.title}\nGoal: ${input.task.goal}\n\n${input.task.instructions}`);
  parts.push(`# Acceptance criteria\n${input.task.acceptance.map((a) => `- ${a}`).join('\n') || '- (none given)'}`);
  if (input.reviseNotes) parts.push(`# Reviewer feedback on your previous attempt — address all of it\n${input.reviseNotes}`);
  return parts.join('\n\n');
}

export class ApiBrain implements Brain {
  readonly simulated = false;

  expectedChars(): number {
    return 7000;
  }

  async propose(call: BrainCall, input: ProposeInput): Promise<Gen> {
    const focus = SEAT_FOCUS[input.seatTitle] ?? 'the soundest way to reach the goal';
    return callClaude({
      model: call.model,
      system: `${COUNCIL_SYSTEM}\nYour seat: ${input.seatTitle}. You pay special attention to ${focus}.`,
      prompt: `The council has been summoned for this goal:\n\n${input.goal}\n\nWrite your proposal in markdown with these sections: Analysis, Proposed framework, Risks, Candidate tasks. Keep it under 600 words.`,
      effort: 'high',
      signal: call.signal,
      onText: call.onText,
    });
  }

  async synthesize(call: BrainCall, input: SynthesizeInput): Promise<Gen & { plan: Plan }> {
    const roster = input.roster
      .map((r) => `- id=${r.id} name=${r.name} model=${r.model ?? 'unknown'} source=${r.source} controllable=${r.controllable} status=${r.status}`)
      .join('\n');
    const proposals = input.proposals.map((p) => `## ${p.seatTitle} (${p.memberName})\n${p.text}`).join('\n\n');
    const res = await callClaudeJson(
      {
        model: call.model,
        system: `${COUNCIL_SYSTEM}\nYou chair the council: you turn the proposals into one executable plan.`,
        prompt: `Goal:\n${input.goal}\n\nProposals from the council:\n\n${proposals}\n\nAvailable workers:\n${roster}\n\nProduce the final plan: 3 to 8 tasks. Each task's instructions must be a detailed, self-contained brief a worker can execute without seeing anything else. Use dependsOn (task keys) only where a task truly needs another's output. Suggest a controllable worker for each task: smaller models (haiku) for small, well-scoped tasks; larger ones (sonnet) for big or subtle tasks.`,
        effort: 'high',
        signal: call.signal,
        onText: call.onText,
        schema: PLAN_JSON_SCHEMA,
      },
      planValidator,
    );
    return { text: res.text, tokensIn: res.tokensIn, tokensOut: res.tokensOut, plan: { ...res.data, tasks: res.data.tasks.slice(0, 8) } };
  }

  async execute(call: BrainCall, input: ExecuteInput): Promise<Gen> {
    return callClaude({
      model: call.model,
      system: WORKER_SYSTEM,
      prompt: executePrompt(input),
      effort: 'medium',
      signal: call.signal,
      onText: call.onText,
    });
  }

  async review(call: BrainCall, input: ReviewInput): Promise<Gen & Review> {
    const res = await callClaudeJson(
      {
        model: call.model,
        system: `${COUNCIL_SYSTEM}\nYou are the Warden: you review worker deliverables against their acceptance criteria. Approve work that meets the criteria; ask for revision only for substantive gaps.`,
        prompt: `Mission goal:\n${input.goal}\n\nTask: ${input.task.title}\nGoal: ${input.task.goal}\nAcceptance criteria:\n${input.task.acceptance.map((a) => `- ${a}`).join('\n')}\n\nAttempt ${input.attempt} deliverable:\n\n${truncate(input.output, 40_000)}`,
        effort: 'medium',
        signal: call.signal,
        onText: call.onText,
        schema: REVIEW_JSON_SCHEMA,
      },
      reviewValidator,
    );
    return { text: res.text, tokensIn: res.tokensIn, tokensOut: res.tokensOut, ...res.data };
  }

  async verdict(call: BrainCall, input: VerdictInput): Promise<Gen> {
    return callClaude({
      model: call.model,
      system: `${COUNCIL_SYSTEM}\nYou chair the council and close the mission.`,
      prompt: `Goal:\n${input.goal}\n\nPlan summary:\n${input.summary}\n\nTask results:\n${input.tasks.map((t) => `- ${t.title}: ${t.status}${t.notes ? ` — ${t.notes}` : ''}`).join('\n')}\n\nWrite a short final verdict in markdown (under 200 words): what was delivered, what remains, and the recommended next step.`,
      effort: 'low',
      signal: call.signal,
      onText: call.onText,
    });
  }
}
