import { execFile } from 'node:child_process';
import fs from 'node:fs/promises';
import type { AgentSource, ProcessInfo } from '../../shared/protocol.ts';
import { isRecord, num, str, truncate } from '../util.ts';

export interface RawProcess {
  pid: number;
  ppid: number;
  cpu: number;
  rssKb: number;
  startedAt?: number;
  args: string;
}

export interface AgentSignature {
  source: AgentSource;
  /** Optional display label (e.g. "Claude Desktop"). */
  label?: string;
}

export interface DetectedProcess {
  source: AgentSource;
  label?: string;
  pid: number;
  cwd?: string;
  info: ProcessInfo;
}

// ── parsing ──────────────────────────────────────────────────────────────

/** Parse ps etime ("[[dd-]hh:]mm:ss") into seconds; undefined when malformed. */
export function parseEtime(etime: string): number | undefined {
  const m = /^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$/.exec(etime.trim());
  if (!m) return undefined;
  const [, d, h, mm, ss] = m;
  return Number(d ?? 0) * 86400 + Number(h ?? 0) * 3600 + Number(mm) * 60 + Number(ss);
}

const PS_LINE = /^\s*(\d+)\s+(\d+)\s+([\d.,]+)\s+(\d+)\s+(\S+)\s+(.*)$/;

export function parsePsLine(line: string, nowMs = Date.now()): RawProcess | undefined {
  const m = PS_LINE.exec(line);
  if (!m) return undefined;
  const secs = parseEtime(m[5]!);
  return {
    pid: Number(m[1]),
    ppid: Number(m[2]),
    cpu: Number(m[3]!.replace(',', '.')) || 0,
    rssKb: Number(m[4]),
    startedAt: secs === undefined ? undefined : nowMs - secs * 1000,
    args: m[6]!.trim(),
  };
}

export function parsePsOutput(out: string, nowMs = Date.now()): RawProcess[] {
  return out.split('\n').map((l) => parsePsLine(l, nowMs)).filter((p): p is RawProcess => p !== undefined);
}

/** Parse the ConvertTo-Json output of Get-CimInstance Win32_Process. */
export function parseWindowsJson(out: string): RawProcess[] {
  let data: unknown;
  try {
    data = JSON.parse(out);
  } catch {
    return [];
  }
  const rows = Array.isArray(data) ? data : [data];
  const result: RawProcess[] = [];
  for (const row of rows) {
    if (!isRecord(row)) continue;
    const pid = num(row.ProcessId);
    if (pid === undefined) continue;
    const created = str(row.CreationDate);
    // CIM dates serialise as "/Date(1712345678901)/".
    const ms = created ? Number(/\/Date\((\d+)/.exec(created)?.[1]) : NaN;
    result.push({
      pid,
      ppid: num(row.ParentProcessId) ?? 0,
      cpu: 0,
      rssKb: Math.round((num(row.WorkingSetSize) ?? 0) / 1024),
      startedAt: Number.isFinite(ms) ? ms : undefined,
      args: str(row.CommandLine) ?? '',
    });
  }
  return result;
}

// ── secrets ──────────────────────────────────────────────────────────────

const SECRET_PATTERNS: Array<[RegExp, string]> = [
  [/(--?[\w-]*(?:api[-_]?key|token|secret|password|passwd|auth)[\w-]*)(=|\s+)("[^"]*"|'[^']*'|\S+)/gi, '$1$2***'],
  [/\b([A-Za-z_][A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|CREDENTIALS?)[A-Za-z0-9_]*)=("[^"]*"|'[^']*'|\S+)/gi, '$1=***'],
  [/\bsk-[A-Za-z0-9_-]{6,}/g, 'sk-***'],
  [/\b(?:ghp|gho|ghs|github_pat|xox[abpr]|AIza)[A-Za-z0-9_-]{10,}/g, '***'],
  [/(\/\/[^/\s:@]+:)[^@\s/]+@/g, '$1***@'],
];

export function stripSecrets(command: string, max = 200): string {
  let out = command;
  for (const [re, rep] of SECRET_PATTERNS) out = out.replace(re, rep);
  return truncate(out, max);
}

// ── signatures ───────────────────────────────────────────────────────────

const RUNTIMES = new Set(['node', 'nodejs', 'bun', 'deno', 'python', 'python3', 'pythonw', 'tsx', 'npx']);

function baseName(p: string): string {
  const b = p.replace(/^["']|["']$/g, '').split(/[\\/]/).pop() ?? p;
  return b.toLowerCase().replace(/\.(exe|cmd|bat|js|mjs|cjs)$/, '');
}

/** Identify a coding-agent process from its command line. Returns null for anything else. */
export function matchSignature(args: string): AgentSignature | null {
  const cmd = args.trim();
  if (!cmd) return null;
  // Electron/Chromium helpers (renderer, gpu, utility…) are never the agent itself.
  if (/\s--type=/.test(cmd)) return null;

  if (/Claude\.app\/Contents\/MacOS\/Claude(\s|$)/.test(cmd) || /[\\/]AnthropicClaude[\\/].*Claude\.exe"?(\s|$)/i.test(cmd)) {
    return { source: 'other', label: 'Claude Desktop' };
  }
  if (/Claude\.app\//.test(cmd) || /Claude Helper/.test(cmd)) return null;
  if (/Cursor\.app\/Contents\/MacOS\/Cursor(\s|$)/.test(cmd) || /[\\/]cursor[\\/]Cursor\.exe"?(\s|$)/i.test(cmd)) {
    return { source: 'cursor', label: 'Cursor' };
  }
  if (/Cursor\.app\/|Cursor Helper/.test(cmd)) return null;

  const tokens = cmd.split(/\s+/);
  const exe = baseName(tokens[0]!);
  let script = exe;
  let rest = tokens.slice(1);
  if (RUNTIMES.has(exe) || /^python\d/.test(exe)) {
    const idx = tokens.findIndex((t, i) => i > 0 && !t.startsWith('-'));
    if (tokens[idx - 1] === '-m' && idx > 0) script = tokens[idx]!.toLowerCase();
    else if (idx > 0) script = baseName(tokens[idx]!);
    rest = idx > 0 ? tokens.slice(idx + 1) : [];
  }
  const joined = cmd.toLowerCase();

  if (joined.includes('@anthropic-ai/claude-code') || script === 'claude') return { source: 'claude-code' };
  if (joined.includes('@openai/codex') || /^codex(-[a-z0-9_]+(-[a-z0-9_]+)*)?$/.test(script)) return { source: 'codex' };
  if (joined.includes('@google/gemini-cli') || script === 'gemini') return { source: 'gemini-cli' };
  if (script === 'aider') return { source: 'aider' };
  if (script === 'ollama' && (rest[0] === 'serve' || rest[0] === 'run')) {
    return { source: 'ollama', label: rest[0] === 'serve' ? 'Ollama server' : undefined };
  }
  if (script === 'cursor-agent') return { source: 'cursor' };
  if (joined.includes('@github/copilot') || script === 'copilot' || script === 'github-copilot-cli') return { source: 'copilot' };
  if (joined.includes('opencode-ai') || script === 'opencode') return { source: 'opencode' };
  if (script === 'goose') return { source: 'goose' };
  return null;
}

// ── collapsing ───────────────────────────────────────────────────────────

export interface CollapsedMatch {
  root: RawProcess;
  signature: AgentSignature;
  cpu: number;
  rssKb: number;
}

/**
 * One entry per agent session: matched processes whose ancestors also match are folded
 * into the top-most matching ancestor, and each root absorbs the CPU/RSS of its subtree.
 */
export function collapseMatches(procs: RawProcess[], match = matchSignature): CollapsedMatch[] {
  const byPid = new Map(procs.map((p) => [p.pid, p]));
  const sigs = new Map<number, AgentSignature>();
  for (const p of procs) {
    const s = match(p.args);
    if (s) sigs.set(p.pid, s);
  }
  const children = new Map<number, RawProcess[]>();
  for (const p of procs) {
    if (p.ppid === p.pid) continue;
    const list = children.get(p.ppid) ?? [];
    list.push(p);
    children.set(p.ppid, list);
  }
  const roots: CollapsedMatch[] = [];
  for (const [pid, signature] of sigs) {
    let cur = byPid.get(pid);
    let hasMatchingAncestor = false;
    const seen = new Set<number>();
    while (cur && !seen.has(cur.pid)) {
      seen.add(cur.pid);
      const parent = byPid.get(cur.ppid);
      if (!parent || parent.pid === cur.pid) break;
      if (sigs.has(parent.pid)) {
        hasMatchingAncestor = true;
        break;
      }
      cur = parent;
    }
    if (hasMatchingAncestor) continue;
    const root = byPid.get(pid)!;
    let cpu = 0;
    let rssKb = 0;
    const stack = [root];
    const visited = new Set<number>();
    while (stack.length) {
      const p = stack.pop()!;
      if (visited.has(p.pid)) continue;
      visited.add(p.pid);
      cpu += p.cpu;
      rssKb += p.rssKb;
      stack.push(...(children.get(p.pid) ?? []));
    }
    roots.push({ root, signature, cpu, rssKb });
  }
  return roots;
}

// ── platform I/O ─────────────────────────────────────────────────────────

function run(cmd: string, args: string[], timeout = 4000): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(cmd, args, { timeout, maxBuffer: 32 * 1024 * 1024, windowsHide: true }, (err, stdout) => {
      if (err && !stdout) reject(err);
      else resolve(stdout);
    });
  });
}

export async function listProcesses(platform = process.platform): Promise<RawProcess[]> {
  if (platform === 'win32') {
    const out = await run(
      'powershell',
      [
        '-NoProfile',
        '-Command',
        'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine,WorkingSetSize,CreationDate | ConvertTo-Json -Compress',
      ],
      10000,
    );
    return parseWindowsJson(out);
  }
  return parsePsOutput(await run('ps', ['-axo', 'pid=,ppid=,pcpu=,rss=,etime=,args=']));
}

const cwdCache = new Map<number, string | null>();

async function resolveCwds(pids: number[], platform: NodeJS.Platform): Promise<void> {
  const missing = pids.filter((p) => !cwdCache.has(p));
  if (!missing.length || platform === 'win32') return;
  if (platform === 'linux') {
    await Promise.all(
      missing.map(async (pid) => {
        try {
          cwdCache.set(pid, await fs.readlink(`/proc/${pid}/cwd`));
        } catch {
          cwdCache.set(pid, null);
        }
      }),
    );
    return;
  }
  // macOS (and other BSDs): one batched lsof call.
  try {
    const out = await run('lsof', ['-a', '-d', 'cwd', '-p', missing.join(','), '-Fn'], 4000);
    let pid: number | undefined;
    for (const line of out.split('\n')) {
      if (line.startsWith('p')) pid = Number(line.slice(1));
      else if (line.startsWith('n') && pid !== undefined) cwdCache.set(pid, line.slice(1));
    }
  } catch {
    // lsof missing or denied: remember the failure so we don't retry every poll.
  }
  for (const pid of missing) if (!cwdCache.has(pid)) cwdCache.set(pid, null);
}

export async function scanProcesses(platform = process.platform): Promise<DetectedProcess[]> {
  const procs = await listProcesses(platform);
  const roots = collapseMatches(procs);
  const alive = new Set(procs.map((p) => p.pid));
  for (const pid of cwdCache.keys()) if (!alive.has(pid)) cwdCache.delete(pid);
  await resolveCwds(roots.map((r) => r.root.pid), platform);
  return roots
    .filter((r) => r.root.pid !== process.pid)
    .map((r) => ({
      source: r.signature.source,
      label: r.signature.label,
      pid: r.root.pid,
      cwd: cwdCache.get(r.root.pid) ?? undefined,
      info: {
        pid: r.root.pid,
        cpu: Math.round(r.cpu * 10) / 10,
        memMb: Math.round(r.rssKb / 1024),
        startedAt: r.root.startedAt,
        command: stripSecrets(r.root.args),
      },
    }));
}
