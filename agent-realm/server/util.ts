import path from 'node:path';

export const now = (): number => Date.now();

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, Math.max(0, max - 1)).trimEnd() + '…';
}

export function firstLine(text: string, max = 120): string {
  const line = text.split('\n').map((l) => l.trim()).find((l) => l.length > 0) ?? '';
  return truncate(line, max);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function str(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

export function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** Short display form of a path: relative to cwd when inside it, basename when still long. */
export function displayPath(p: string, cwd?: string, max = 48): string {
  let out = p;
  if (cwd && (p === cwd || p.startsWith(cwd.endsWith(path.sep) ? cwd : cwd + path.sep) || p.startsWith(cwd + '/'))) {
    out = p.slice(cwd.length).replace(/^[\\/]+/, '') || '.';
  }
  if (out.length > max) out = out.split(/[\\/]/).filter(Boolean).pop() ?? out;
  return truncate(out, max);
}

export function projectName(cwd?: string): string | undefined {
  if (!cwd) return undefined;
  const base = cwd.split(/[\\/]/).filter(Boolean).pop();
  return base || undefined;
}

export class AbortedError extends Error {
  constructor() {
    super('Aborted');
    this.name = 'AbortedError';
  }
}

export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new AbortedError());
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, Math.max(0, ms));
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(new AbortedError());
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/** FNV-1a 32-bit hash; deterministic across runs and platforms. */
export function hash32(input: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Tiny deterministic PRNG seeded from a string (mulberry32). */
export function seededRandom(seed: string): () => number {
  let a = hash32(seed);
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function pick<T>(items: readonly T[], rand: () => number): T {
  return items[Math.floor(rand() * items.length) % items.length]!;
}
