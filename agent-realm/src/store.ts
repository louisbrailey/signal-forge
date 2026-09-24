import type { Activity, Agent, ClientMessage, Mission, RealmInfo, ServerMessage, Task } from '../shared/protocol';

export type ConnState = 'connecting' | 'open' | 'closed';

export interface FeedLine {
  id: string;
  ts: number;
  agentId?: string;
  text: string;
  tone: 'activity' | 'council' | 'system' | 'success' | 'warn' | 'error';
}

type Listener = () => void;

/** Client-side mirror of the realm. Applies server messages and notifies subscribers (batched per frame). */
export class Store {
  info: RealmInfo | null = null;
  agents = new Map<string, Agent>();
  tasks = new Map<string, Task>();
  missions = new Map<string, Mission>();
  feed: FeedLine[] = [];
  conn: ConnState = 'connecting';
  selectedId: string | null = null;
  followId: string | null = null;
  missionId: string | null = null; // mission shown in the quest log / council chamber
  skew = 0; // serverTime - Date.now()

  private listeners = new Set<Listener>();
  private queued = false;
  private ws: WebSocket | null = null;
  private retry = 0;
  readonly onServer = new Set<(m: ServerMessage) => void>();

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  changed(): void {
    if (this.queued) return;
    this.queued = true;
    requestAnimationFrame(() => {
      this.queued = false;
      this.listeners.forEach((fn) => fn());
    });
  }

  connect(): void {
    const url = new URL('/ws', location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = new URLSearchParams(location.search).get('token');
    if (token) url.searchParams.set('token', token);
    this.conn = 'connecting';
    this.changed();
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => { this.retry = 0; this.conn = 'open'; this.changed(); };
    ws.onmessage = (ev) => {
      let msg: ServerMessage;
      try { msg = JSON.parse(String(ev.data)) as ServerMessage; } catch { return; }
      this.apply(msg);
      this.onServer.forEach((fn) => fn(msg));
    };
    ws.onclose = () => {
      this.conn = 'closed';
      this.changed();
      const wait = Math.min(10_000, 500 * 2 ** this.retry++);
      setTimeout(() => this.connect(), wait);
    };
  }

  send(msg: ClientMessage): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  get now(): number { return Date.now() + this.skew; }

  private apply(msg: ServerMessage): void {
    switch (msg.type) {
      case 'snapshot': {
        const d = msg.data;
        this.info = d.info;
        this.skew = d.serverTime - Date.now();
        this.agents = new Map(d.agents.map((a) => [a.id, a]));
        this.tasks = new Map(d.tasks.map((t) => [t.id, t]));
        this.missions = new Map(d.missions.map((m) => [m.id, m]));
        if (!this.missionId || !this.missions.has(this.missionId)) this.missionId = this.latestMission()?.id ?? null;
        break;
      }
      case 'info': this.info = msg.info; break;
      case 'agent': {
        const prev = this.agents.get(msg.agent.id);
        this.agents.set(msg.agent.id, msg.agent);
        if (!prev && msg.agent.live) this.log({ agentId: msg.agent.id, text: `joined the realm`, tone: 'success' });
        break;
      }
      case 'agent_removed':
        this.agents.delete(msg.id);
        if (this.selectedId === msg.id) this.selectedId = null;
        if (this.followId === msg.id) this.followId = null;
        break;
      case 'activity': this.onActivity(msg.activity); break;
      case 'task': this.tasks.set(msg.task.id, msg.task); break;
      case 'mission': {
        const prev = this.missions.get(msg.mission.id);
        this.missions.set(msg.mission.id, msg.mission);
        if (!prev) this.missionId = msg.mission.id;
        if (prev && prev.status !== msg.mission.status) {
          const tone = msg.mission.status === 'complete' ? 'success' : msg.mission.status === 'failed' ? 'error' : 'council';
          this.log({ text: `Mission “${short(msg.mission.goal, 60)}” → ${msg.mission.status}`, tone });
        }
        break;
      }
      case 'delegate': {
        const t = this.tasks.get(msg.taskId);
        this.log({ agentId: msg.fromId, text: `assigned “${short(t?.title ?? 'a task', 50)}” to ${this.agents.get(msg.toId)?.name ?? 'a worker'}`, tone: 'council' });
        break;
      }
      case 'deliver': {
        const t = this.tasks.get(msg.taskId);
        this.log({ agentId: msg.fromId, text: `delivered “${short(t?.title ?? 'work', 50)}” for review`, tone: 'success' });
        break;
      }
      case 'toast': this.log({ text: msg.text, tone: msg.level === 'info' ? 'system' : msg.level }); break;
    }
    this.changed();
  }

  private onActivity(a: Activity): void {
    const ag = this.agents.get(a.agentId);
    if (ag) {
      ag.recent = [...ag.recent.filter((r) => r.id !== a.id), a].slice(-40);
      ag.lastActivityAt = a.ts;
      if (a.kind !== 'system') ag.currentAction = a.text;
    }
    if (a.kind !== 'think' || !ag || ag.role === 'council') {
      this.log({ agentId: a.agentId, text: a.text, tone: ag?.role === 'council' ? 'council' : 'activity' });
    }
  }

  log(l: Omit<FeedLine, 'id' | 'ts'>): void {
    this.feed.push({ ...l, id: Math.random().toString(36).slice(2), ts: Date.now() });
    if (this.feed.length > 200) this.feed.splice(0, this.feed.length - 200);
  }

  latestMission(): Mission | undefined {
    return [...this.missions.values()].sort((a, b) => b.createdAt - a.createdAt)[0];
  }

  sortedAgents(): Agent[] {
    const rank = { working: 0, thinking: 1, waiting: 2, error: 3, done: 4, idle: 5, offline: 6 } as const;
    return [...this.agents.values()].sort(
      (a, b) =>
        (a.role === b.role ? 0 : a.role === 'council' ? -1 : 1) ||
        Number(b.live) - Number(a.live) ||
        rank[a.status] - rank[b.status] ||
        a.name.localeCompare(b.name),
    );
  }

  missionTasks(m: Mission): Task[] {
    return m.taskIds.map((id) => this.tasks.get(id)).filter((t): t is Task => !!t);
  }
}

export function short(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
