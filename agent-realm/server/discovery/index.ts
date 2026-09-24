import path from 'node:path';
import type { Agent, DiscoveryStatus } from '../../shared/protocol.ts';
import { makeAgent } from '../agents.ts';
import type { OverrideStore } from '../config.ts';
import { titleFor } from '../identity.ts';
import type { Realm } from '../state.ts';
import { projectName } from '../util.ts';
import { ClaudeCodeScanner } from './claudeCode.ts';
import { CodexScanner } from './codex.ts';
import { OllamaScanner } from './ollama.ts';
import { scanProcesses, type DetectedProcess } from './processes.ts';
import type { DetectedAgent } from './types.ts';

const POLL_MS = 2500;
const LEAVE_MS = 8000;

function sameDir(a?: string, b?: string): boolean {
  if (!a || !b) return false;
  const norm = (p: string): string => path.resolve(p).replace(/[\\/]+$/, '').toLowerCase();
  return norm(a) === norm(b);
}

function processAgent(p: DetectedProcess): DetectedAgent {
  return {
    id: `${p.source}:pid:${p.pid}`,
    source: p.source,
    label: p.label,
    status: p.info.cpu > 3 ? 'working' : 'idle',
    cwd: p.cwd,
    process: p.info,
    activities: [],
  };
}

/** Attach processes to transcript sessions (same source + cwd); leftovers become their own agents. */
export function mergeProcesses(sessions: DetectedAgent[], procs: DetectedProcess[]): DetectedAgent[] {
  const out = sessions.map((s) => ({ ...s }));
  const claimed = new Set<DetectedAgent>();
  for (const p of procs) {
    const candidates = out
      .filter((s) => s.source === p.source && !claimed.has(s) && sameDir(s.cwd, p.cwd))
      .sort((a, b) => (b.lastActivityAt ?? 0) - (a.lastActivityAt ?? 0));
    const target = candidates[0];
    if (target) {
      target.process = p.info;
      claimed.add(target);
    } else {
      out.push(processAgent(p));
    }
  }
  return out;
}

export class Discovery {
  private claude = new ClaudeCodeScanner();
  private codex = new CodexScanner();
  private ollama = new OllamaScanner();
  private known = new Set<string>();
  private timer?: NodeJS.Timeout;
  private running = false;
  private lastStatuses = '';

  constructor(
    private readonly realm: Realm,
    private readonly overrides: OverrideStore,
  ) {}

  start(): Promise<void> {
    const first = this.poll();
    this.timer = setInterval(() => void this.poll(), POLL_MS);
    this.timer.unref?.();
    return first;
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
  }

  /** Number of real (live, detected) agents currently present. */
  liveCount(): number {
    let n = 0;
    for (const id of this.known) if (this.realm.getAgent(id)?.status !== 'offline') n++;
    return n;
  }

  async poll(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      const statuses: DiscoveryStatus[] = [];
      const guard = async <T>(source: string, fn: () => Promise<T>, count: (v: T) => number, note?: (v: T) => string | undefined): Promise<T | undefined> => {
        try {
          const v = await fn();
          statuses.push({ source, ok: true, count: count(v), ...(note?.(v) ? { note: note(v) } : {}) });
          return v;
        } catch (err) {
          statuses.push({ source, ok: false, count: 0, note: err instanceof Error ? err.message.slice(0, 120) : 'failed' });
          return undefined;
        }
      };

      const [procs, claude, codex, ollama] = await Promise.all([
        guard('processes', () => scanProcesses(), (v) => v.length),
        guard('claude-code transcripts', () => this.claude.scan(), (v) => v.length),
        guard('codex sessions', () => this.codex.scan(), (v) => v.length),
        this.ollama.scan().then(
          (v) => {
            statuses.push(v ? { source: 'ollama', ok: true, count: v.length } : { source: 'ollama', ok: false, count: 0, note: 'not running' });
            return v;
          },
          () => {
            statuses.push({ source: 'ollama', ok: false, count: 0, note: 'not running' });
            return null;
          },
        ),
      ]);

      let processes = procs ?? [];
      const ollamaModels = ollama ?? [];
      if (ollamaModels.length) {
        const server = processes.find((p) => p.source === 'ollama' && p.label === 'Ollama server');
        if (server) for (const m of ollamaModels) m.process = server.info;
        processes = processes.filter((p) => p.source !== 'ollama');
      }
      const detected = [...mergeProcesses([...(claude ?? []), ...(codex ?? [])], processes), ...ollamaModels];
      this.reconcile(detected);
      const order = ['processes', 'claude-code transcripts', 'codex sessions', 'ollama'];
      statuses.sort((a, b) => order.indexOf(a.source) - order.indexOf(b.source));
      const serialized = JSON.stringify(statuses);
      if (serialized !== this.lastStatuses) {
        this.lastStatuses = serialized;
        this.realm.setInfo({ discovery: statuses });
      }
    } finally {
      this.running = false;
    }
  }

  private reconcile(detected: DetectedAgent[]): void {
    const present = new Set<string>();
    for (const d of detected) {
      present.add(d.id);
      const project = projectName(d.cwd);
      const existing = this.realm.getAgent(d.id);
      let agent: Agent;
      if (!existing) {
        agent = makeAgent(
          {
            id: d.id,
            source: d.source,
            model: d.model,
            live: true,
            controllable: false,
            status: d.status,
            project,
            cwd: d.cwd,
            title: d.label && d.source !== 'claude-code' ? d.label : undefined,
            takenNames: this.realm.takenNames(),
          },
          this.overrides,
        );
        if (d.lastActivityAt) agent.lastActivityAt = d.lastActivityAt;
        this.realm.upsertAgent(agent);
      } else {
        const title = d.label && d.source !== 'claude-code' ? d.label : titleFor({ ...existing, model: d.model ?? existing.model, project: project ?? existing.project });
        const model = d.model ?? existing.model;
        this.realm.patchAgent(d.id, {
          status: d.status,
          model,
          cwd: d.cwd ?? existing.cwd,
          project: project ?? existing.project,
          process: d.process,
          title,
        });
      }
      for (const a of d.activities) this.realm.pushActivity(d.id, { kind: a.kind, text: a.text, detail: a.detail, ts: a.ts });
      if (d.tokensIn !== undefined || d.tokensOut !== undefined) {
        const cur = this.realm.getAgent(d.id);
        if (cur) {
          this.realm.patchAgent(d.id, {
            stats: { ...cur.stats, tokensIn: d.tokensIn ?? cur.stats.tokensIn, tokensOut: d.tokensOut ?? cur.stats.tokensOut },
            ...(d.lastActivityAt ? { lastActivityAt: Math.max(cur.lastActivityAt, d.lastActivityAt) } : {}),
          });
        }
      }
    }
    for (const id of this.known) {
      if (!present.has(id)) this.realm.retireAgent(id, LEAVE_MS);
    }
    // Retired agents drop out of `known` once they are actually removed.
    for (const id of [...this.known]) if (!this.realm.getAgent(id)) this.known.delete(id);
    for (const id of present) this.known.add(id);
  }
}
