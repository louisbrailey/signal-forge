import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';
import {
  RECENT_ACTIVITY_CAP,
  type Activity,
  type ActivityKind,
  type Agent,
  type Mission,
  type RealmInfo,
  type RealmSnapshot,
  type ServerMessage,
  type Task,
  type ToastLevel,
} from '../shared/protocol.ts';
import { now, truncate } from './util.ts';

/** Minimum gap between two 'agent' broadcasts for the same agent (≤4/s). */
const AGENT_BROADCAST_MS = 250;
const DETAIL_CAP = 2000;
const TOOL_KINDS: ReadonlySet<ActivityKind> = new Set(['read', 'edit', 'bash', 'search', 'web', 'tool', 'delegate']);

export interface ActivityInput {
  kind: ActivityKind;
  text: string;
  detail?: string;
  taskId?: string;
  ts?: number;
  /** Update the speech bubble (default true). */
  setAction?: boolean;
}

type RealmEvents = { message: [ServerMessage] };

export class Realm extends EventEmitter<RealmEvents> {
  readonly agents = new Map<string, Agent>();
  readonly tasks = new Map<string, Task>();
  readonly missions = new Map<string, Mission>();
  info: RealmInfo;

  private lastAgentSend = new Map<string, number>();
  private pendingAgent = new Map<string, NodeJS.Timeout>();
  private retireTimers = new Map<string, NodeJS.Timeout>();

  constructor(info: RealmInfo) {
    super();
    this.info = info;
  }

  static newId(): string {
    return randomUUID();
  }

  broadcast(msg: ServerMessage): void {
    this.emit('message', msg);
  }

  snapshot(): RealmSnapshot {
    return {
      info: this.info,
      agents: [...this.agents.values()],
      tasks: [...this.tasks.values()],
      missions: [...this.missions.values()],
      serverTime: now(),
    };
  }

  setInfo(patch: Partial<RealmInfo>): void {
    this.info = { ...this.info, ...patch };
    this.broadcast({ type: 'info', info: this.info });
  }

  // ── agents ──────────────────────────────────────────────────────────

  takenNames(): Set<string> {
    return new Set([...this.agents.values()].map((a) => a.name));
  }

  getAgent(id: string): Agent | undefined {
    return this.agents.get(id);
  }

  upsertAgent(agent: Agent): Agent {
    const timer = this.retireTimers.get(agent.id);
    if (timer && agent.status !== 'offline') {
      clearTimeout(timer);
      this.retireTimers.delete(agent.id);
    }
    this.agents.set(agent.id, agent);
    this.scheduleAgentBroadcast(agent.id);
    return agent;
  }

  /** Shallow-merge a patch into an existing agent; no-op when unknown. */
  patchAgent(id: string, patch: Partial<Agent>): Agent | undefined {
    const current = this.agents.get(id);
    if (!current) return undefined;
    return this.upsertAgent({ ...current, ...patch });
  }

  removeAgent(id: string): void {
    const pending = this.pendingAgent.get(id);
    if (pending) clearTimeout(pending);
    this.pendingAgent.delete(id);
    this.lastAgentSend.delete(id);
    const timer = this.retireTimers.get(id);
    if (timer) clearTimeout(timer);
    this.retireTimers.delete(id);
    if (this.agents.delete(id)) this.broadcast({ type: 'agent_removed', id });
  }

  /** Mark offline now and remove after `delayMs`, so clients can animate the departure. */
  retireAgent(id: string, delayMs = 8000): void {
    if (!this.agents.has(id) || this.retireTimers.has(id)) return;
    this.patchAgent(id, { status: 'offline', currentAction: undefined });
    const timer = setTimeout(() => {
      this.retireTimers.delete(id);
      this.removeAgent(id);
    }, delayMs);
    timer.unref?.();
    this.retireTimers.set(id, timer);
  }

  isRetiring(id: string): boolean {
    return this.retireTimers.has(id);
  }

  pushActivity(agentId: string, input: ActivityInput): Activity | undefined {
    const agent = this.agents.get(agentId);
    if (!agent) return undefined;
    const activity: Activity = {
      id: randomUUID(),
      agentId,
      ts: input.ts ?? now(),
      kind: input.kind,
      text: truncate(input.text.replace(/\s+/g, ' ').trim(), 160),
      ...(input.detail ? { detail: truncate(input.detail, DETAIL_CAP) } : {}),
      ...(input.taskId ? { taskId: input.taskId } : {}),
    };
    const recent = [...agent.recent, activity];
    if (recent.length > RECENT_ACTIVITY_CAP) recent.splice(0, recent.length - RECENT_ACTIVITY_CAP);
    const stats = TOOL_KINDS.has(activity.kind) ? { ...agent.stats, toolCalls: agent.stats.toolCalls + 1 } : agent.stats;
    this.agents.set(agentId, {
      ...agent,
      recent,
      stats,
      lastActivityAt: Math.max(agent.lastActivityAt, activity.ts),
      currentAction: input.setAction === false ? agent.currentAction : activity.text,
    });
    this.broadcast({ type: 'activity', activity });
    this.scheduleAgentBroadcast(agentId);
    return activity;
  }

  addUsage(agentId: string, tokensIn: number, tokensOut: number): void {
    const agent = this.agents.get(agentId);
    if (!agent) return;
    this.patchAgent(agentId, {
      stats: { ...agent.stats, tokensIn: agent.stats.tokensIn + tokensIn, tokensOut: agent.stats.tokensOut + tokensOut },
    });
  }

  private scheduleAgentBroadcast(id: string): void {
    if (this.pendingAgent.has(id)) return;
    const elapsed = now() - (this.lastAgentSend.get(id) ?? 0);
    const send = (): void => {
      this.pendingAgent.delete(id);
      const agent = this.agents.get(id);
      if (!agent) return;
      this.lastAgentSend.set(id, now());
      this.broadcast({ type: 'agent', agent });
    };
    if (elapsed >= AGENT_BROADCAST_MS) {
      send();
      return;
    }
    const timer = setTimeout(send, AGENT_BROADCAST_MS - elapsed);
    timer.unref?.();
    this.pendingAgent.set(id, timer);
  }

  // ── tasks & missions ────────────────────────────────────────────────

  upsertTask(task: Task): Task {
    const next = { ...task, updatedAt: now() };
    this.tasks.set(task.id, next);
    this.broadcast({ type: 'task', task: next });
    return next;
  }

  patchTask(id: string, patch: Partial<Task>): Task | undefined {
    const current = this.tasks.get(id);
    return current ? this.upsertTask({ ...current, ...patch }) : undefined;
  }

  upsertMission(mission: Mission): Mission {
    const next = { ...mission, updatedAt: now() };
    this.missions.set(mission.id, next);
    this.broadcast({ type: 'mission', mission: next });
    return next;
  }

  patchMission(id: string, patch: Partial<Mission>): Mission | undefined {
    const current = this.missions.get(id);
    return current ? this.upsertMission({ ...current, ...patch }) : undefined;
  }

  toast(level: ToastLevel, text: string): void {
    this.broadcast({ type: 'toast', level, text });
  }

  /** Cancel pending timers (used on shutdown and in tests). */
  dispose(): void {
    for (const t of this.pendingAgent.values()) clearTimeout(t);
    for (const t of this.retireTimers.values()) clearTimeout(t);
    this.pendingAgent.clear();
    this.retireTimers.clear();
  }
}
