import type { ActivityKind, AgentSource, AgentStatus, ProcessInfo } from '../../shared/protocol.ts';

export interface ActivityDraft {
  kind: ActivityKind;
  text: string;
  detail?: string;
  ts: number;
}

/** What a scanner reports about one agent in one poll. */
export interface DetectedAgent {
  id: string;
  source: AgentSource;
  status: AgentStatus;
  label?: string;
  model?: string;
  cwd?: string;
  process?: ProcessInfo;
  lastActivityAt?: number;
  /** New activities since the previous poll (oldest first). */
  activities: ActivityDraft[];
  tokensIn?: number;
  tokensOut?: number;
}

export const ACTIVE_WINDOW_MS = 30 * 60 * 1000;
export const WORKING_WINDOW_MS = 20 * 1000;
export const IDLE_WINDOW_MS = 10 * 60 * 1000;

export function statusByRecency(lastActivityAt: number, nowMs: number, busy: AgentStatus = 'working'): AgentStatus {
  const age = nowMs - lastActivityAt;
  if (age < WORKING_WINDOW_MS) return busy;
  return 'idle';
}
