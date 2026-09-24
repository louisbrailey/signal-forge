import type { Agent, AgentRole, AgentSource, AgentStatus } from '../shared/protocol.ts';
import type { OverrideStore } from './config.ts';
import { nameFor, skinFor, titleFor } from './identity.ts';
import { now } from './util.ts';

export interface NewAgentInput {
  id: string;
  source: AgentSource;
  role?: AgentRole;
  model?: string;
  live: boolean;
  controllable: boolean;
  status?: AgentStatus;
  title?: string;
  project?: string;
  cwd?: string;
  chair?: boolean;
  /** Names already in use, so the new villager gets a distinct one. */
  takenNames?: ReadonlySet<string>;
}

/** Build a fresh Agent with deterministic identity, applying persisted overrides. */
export function makeAgent(input: NewAgentInput, overrides?: OverrideStore): Agent {
  const o = overrides?.get(input.id) ?? {};
  const role = o.role ?? input.role ?? 'worker';
  const t = now();
  const base = {
    source: input.source,
    role,
    model: input.model,
    project: input.project,
    live: input.live,
  };
  return {
    id: input.id,
    name: o.name ?? nameFor(input.id, input.takenNames),
    title: input.title ?? titleFor(base),
    role,
    source: input.source,
    ...(input.model ? { model: input.model } : {}),
    status: input.status ?? 'idle',
    live: input.live,
    controllable: input.controllable,
    skin: skinFor({ id: input.id, source: input.source, role, model: input.model, chair: input.chair && role === 'council' }),
    ...(input.project ? { project: input.project } : {}),
    ...(input.cwd ? { cwd: input.cwd } : {}),
    lastActivityAt: t,
    createdAt: t,
    stats: { toolCalls: 0, tasksDone: 0, tokensIn: 0, tokensOut: 0 },
    recent: [],
  };
}
