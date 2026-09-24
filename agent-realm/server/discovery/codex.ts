import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { displayPath, firstLine, isRecord, num, str, truncate } from '../util.ts';
import { JsonlTailer } from './jsonlTail.ts';
import { ACTIVE_WINDOW_MS, statusByRecency, type ActivityDraft, type DetectedAgent } from './types.ts';

function parseArgs(raw: unknown): Record<string, unknown> {
  if (isRecord(raw)) return raw;
  if (typeof raw !== 'string') return {};
  try {
    const v: unknown = JSON.parse(raw);
    return isRecord(v) ? v : {};
  } catch {
    return {};
  }
}

function commandText(cmd: unknown): string | undefined {
  if (typeof cmd === 'string') return cmd;
  if (!Array.isArray(cmd)) return undefined;
  const parts = cmd.filter((c): c is string => typeof c === 'string');
  // ["bash","-lc","npm test"] → "npm test"
  if (parts.length >= 3 && /(^|\/)(ba|z)?sh$/.test(parts[0]!) && parts[1]!.startsWith('-')) return parts.slice(2).join(' ');
  return parts.join(' ');
}

/** Map one Codex rollout line to activities. Never throws. */
export function codexEntryToActivities(entry: unknown, cwd?: string): ActivityDraft[] {
  try {
    if (!isRecord(entry)) return [];
    const ts = Date.parse(str(entry.timestamp) ?? '') || Date.now();
    const payload = isRecord(entry.payload) ? entry.payload : entry;
    const ptype = str(payload.type);
    if (entry.type !== 'response_item' && entry.type !== undefined) return [];
    if (ptype === 'function_call' || ptype === 'custom_tool_call' || ptype === 'local_shell_call') {
      const name = str(payload.name) ?? (ptype === 'local_shell_call' ? 'shell' : 'tool');
      const args = parseArgs(payload.arguments ?? payload.input ?? payload.action);
      if (name === 'shell' || name === 'exec_command' || name === 'container.exec' || ptype === 'local_shell_call') {
        const cmd = commandText(args.command ?? args.cmd);
        return [{ kind: 'bash', text: cmd ? `Bash: ${firstLine(cmd, 80)}` : 'Shell', ts }];
      }
      if (name === 'apply_patch') {
        const patch = typeof payload.input === 'string' ? payload.input : str(args.input) ?? '';
        const file = /\*\*\* (?:Update|Add|Delete) File: (.+)/.exec(patch)?.[1];
        return [{ kind: 'edit', text: file ? `Edit ${displayPath(file.trim(), cwd)}` : 'Apply patch', ts }];
      }
      if (name === 'update_plan') return [{ kind: 'plan', text: 'Update plan', ts }];
      if (name.includes('search')) return [{ kind: 'web', text: truncate(name, 60), ts }];
      if (name === 'read_file' || name === 'view_image') return [{ kind: 'read', text: truncate(name, 60), ts }];
      return [{ kind: 'tool', text: truncate(name, 60), ts }];
    }
    if (ptype === 'web_search_call') return [{ kind: 'web', text: 'Web search', ts }];
    if (ptype === 'reasoning') return [{ kind: 'think', text: 'Reasoning…', ts }];
    if (ptype === 'message' && payload.role === 'assistant' && Array.isArray(payload.content)) {
      const text = payload.content.map((c) => (isRecord(c) ? str(c.text) ?? '' : '')).join('\n');
      if (text.trim()) return [{ kind: 'message', text: firstLine(text, 120), detail: truncate(text, 2000), ts }];
    }
    return [];
  } catch {
    return [];
  }
}

interface CodexSession {
  id: string;
  cwd?: string;
  model?: string;
  lastActivityAt: number;
  pending: ActivityDraft[];
  tokensIn: number;
  tokensOut: number;
}

export function codexHome(env: NodeJS.ProcessEnv = process.env): string {
  return env.CODEX_HOME?.trim() || path.join(os.homedir(), '.codex');
}

async function listRecentRollouts(root: string, nowMs: number): Promise<Array<{ file: string; size: number; mtime: number }>> {
  // Rollouts live in sessions/YYYY/MM/DD/; only the last two days can hold active sessions.
  const dirs = new Set<string>();
  for (const offset of [0, 1]) {
    const d = new Date(nowMs - offset * 86400000);
    const y = String(d.getFullYear());
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    dirs.add(path.join(root, y, m, day));
  }
  dirs.add(root);
  const out: Array<{ file: string; size: number; mtime: number }> = [];
  for (const dir of dirs) {
    let names: string[];
    try {
      names = await fs.readdir(dir);
    } catch {
      continue;
    }
    for (const name of names) {
      if (!name.endsWith('.jsonl')) continue;
      const file = path.join(dir, name);
      try {
        const st = await fs.stat(file);
        if (nowMs - st.mtimeMs <= ACTIVE_WINDOW_MS) out.push({ file, size: st.size, mtime: st.mtimeMs });
      } catch {
        // vanished
      }
    }
  }
  return out;
}

export class CodexScanner {
  private tailer = new JsonlTailer();
  private sessions = new Map<string, CodexSession>();

  constructor(private readonly root = path.join(codexHome(), 'sessions')) {}

  async scan(nowMs = Date.now()): Promise<DetectedAgent[]> {
    const files = await listRecentRollouts(this.root, nowMs);
    const seen = new Set<string>();
    for (const { file, size, mtime } of files) {
      seen.add(file);
      const { lines, firstRead } = await this.tailer.read(file, size);
      const s = this.sessions.get(file) ?? {
        id: /([0-9a-f]{8}-[0-9a-f-]{27})/i.exec(path.basename(file))?.[1] ?? path.basename(file, '.jsonl'),
        lastActivityAt: mtime,
        pending: [],
        tokensIn: 0,
        tokensOut: 0,
      };
      this.sessions.set(file, s);
      for (const line of lines) {
        if (!isRecord(line)) continue;
        const payload = isRecord(line.payload) ? line.payload : line;
        if (line.type === 'session_meta' || (line.type === undefined && str(line.id) && str(line.timestamp) && !payload.type)) {
          s.cwd = str(payload.cwd) ?? s.cwd;
          const id = str(payload.id);
          if (id) s.id = id;
        } else if (line.type === 'turn_context') {
          s.cwd = str(payload.cwd) ?? s.cwd;
          s.model = str(payload.model) ?? s.model;
        } else if (line.type === 'event_msg' && payload.type === 'token_count' && isRecord(payload.info)) {
          const total = payload.info.total_token_usage;
          if (isRecord(total)) {
            s.tokensIn = num(total.input_tokens) ?? s.tokensIn;
            s.tokensOut = num(total.output_tokens) ?? s.tokensOut;
          }
        }
        const ts = Date.parse(str(line.timestamp) ?? '');
        const acts = codexEntryToActivities(line, s.cwd);
        if (acts.length && Number.isFinite(ts)) s.lastActivityAt = Math.max(s.lastActivityAt, ts);
        s.pending.push(...acts);
      }
      if (firstRead && s.pending.length > 12) s.pending = s.pending.slice(-12);
    }
    this.tailer.forget(seen);

    const result: DetectedAgent[] = [];
    for (const [file, s] of this.sessions) {
      if (!seen.has(file)) {
        this.sessions.delete(file);
        continue;
      }
      result.push({
        id: `codex:${s.id}`,
        source: 'codex',
        status: statusByRecency(s.lastActivityAt, nowMs),
        model: s.model,
        cwd: s.cwd,
        lastActivityAt: s.lastActivityAt,
        activities: s.pending,
        tokensIn: s.tokensIn,
        tokensOut: s.tokensOut,
      });
      s.pending = [];
    }
    return result;
  }
}
