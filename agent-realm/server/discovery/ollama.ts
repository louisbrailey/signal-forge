import { isRecord, num, str } from '../util.ts';
import type { DetectedAgent } from './types.ts';

const OLLAMA_URL = process.env.OLLAMA_HOST_URL ?? 'http://127.0.0.1:11434';
const BUSY_MS = 20_000;

export interface OllamaModel {
  name: string;
  expiresAt?: number;
  sizeMb?: number;
}

export function parseOllamaPs(body: unknown): OllamaModel[] {
  if (!isRecord(body) || !Array.isArray(body.models)) return [];
  const out: OllamaModel[] = [];
  for (const m of body.models) {
    if (!isRecord(m)) continue;
    const name = str(m.name) ?? str(m.model);
    if (!name) continue;
    const expires = Date.parse(str(m.expires_at) ?? '');
    const size = num(m.size);
    out.push({ name, expiresAt: Number.isFinite(expires) ? expires : undefined, sizeMb: size ? Math.round(size / 1048576) : undefined });
  }
  return out;
}

export class OllamaScanner {
  /** name → { expiresAt seen last poll, when it last moved } */
  private seen = new Map<string, { expiresAt?: number; bumpedAt: number }>();

  /** Returns null when the Ollama server is not reachable. */
  async scan(nowMs = Date.now()): Promise<DetectedAgent[] | null> {
    let body: unknown;
    try {
      const res = await fetch(`${OLLAMA_URL}/api/ps`, { signal: AbortSignal.timeout(1000) });
      if (!res.ok) return null;
      body = await res.json();
    } catch {
      return null;
    }
    const models = parseOllamaPs(body);
    const next = new Map<string, { expiresAt?: number; bumpedAt: number }>();
    const result: DetectedAgent[] = [];
    for (const m of models) {
      const prev = this.seen.get(m.name);
      // keep_alive pushes expires_at forward on every request, so a moving value means recent use.
      const bumped = !prev || (m.expiresAt !== undefined && prev.expiresAt !== undefined && m.expiresAt > prev.expiresAt + 500);
      const bumpedAt = bumped ? (prev ? nowMs : nowMs - BUSY_MS) : prev.bumpedAt;
      next.set(m.name, { expiresAt: m.expiresAt, bumpedAt });
      const working = nowMs - bumpedAt < BUSY_MS;
      result.push({
        id: `ollama:${m.name}`,
        source: 'ollama',
        model: m.name,
        status: working ? 'working' : 'idle',
        lastActivityAt: bumpedAt,
        activities: bumped && prev ? [{ kind: 'think', text: `Generating with ${m.name}`, ts: nowMs }] : [],
      });
    }
    this.seen = next;
    return result;
  }
}
