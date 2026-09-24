import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import type { ActivityKind } from '../../shared/protocol.ts';
import { displayPath, firstLine, isRecord, num, str, truncate } from '../util.ts';
import { JsonlTailer } from './jsonlTail.ts';
import { ACTIVE_WINDOW_MS, statusByRecency, type ActivityDraft, type DetectedAgent } from './types.ts';

// ── pure mapping (unit-tested) ────────────────────────────────────────────

export function toolKind(name: string): ActivityKind {
  switch (name) {
    case 'Read':
    case 'NotebookRead':
      return 'read';
    case 'Glob':
    case 'Grep':
    case 'LS':
    case 'ToolSearch':
      return 'search';
    case 'Edit':
    case 'Write':
    case 'MultiEdit':
    case 'NotebookEdit':
      return 'edit';
    case 'Bash':
    case 'BashOutput':
    case 'KillShell':
      return 'bash';
    case 'WebFetch':
    case 'WebSearch':
      return 'web';
    case 'Task':
    case 'Agent':
      return 'delegate';
    case 'TodoWrite':
    case 'ExitPlanMode':
      return 'plan';
    default:
      return 'tool';
  }
}

function inputStr(input: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const k of keys) {
    const v = str(input[k]);
    if (v && v.trim()) return v.trim();
  }
  return undefined;
}

/** One-line description of a tool call, e.g. "Edit src/app.ts" or "Bash: npm test". */
export function describeToolUse(name: string, rawInput: unknown, cwd?: string): string {
  const input = isRecord(rawInput) ? rawInput : {};
  const file = inputStr(input, 'file_path', 'notebook_path', 'path');
  switch (name) {
    case 'Read':
    case 'Edit':
    case 'Write':
    case 'MultiEdit':
    case 'NotebookEdit':
      return file ? `${name} ${displayPath(file, cwd)}` : name;
    case 'Bash': {
      const cmd = inputStr(input, 'command');
      return cmd ? `Bash: ${firstLine(cmd, 80)}` : 'Bash';
    }
    case 'Grep': {
      const pattern = inputStr(input, 'pattern');
      return pattern ? `Grep '${truncate(pattern, 60)}'` : 'Grep';
    }
    case 'Glob': {
      const pattern = inputStr(input, 'pattern');
      return pattern ? `Glob ${truncate(pattern, 60)}` : 'Glob';
    }
    case 'WebFetch': {
      const url = inputStr(input, 'url');
      let host = url;
      try {
        if (url) host = new URL(url).host;
      } catch {
        // keep raw url
      }
      return host ? `WebFetch ${truncate(host, 60)}` : 'WebFetch';
    }
    case 'WebSearch': {
      const q = inputStr(input, 'query');
      return q ? `WebSearch '${truncate(q, 60)}'` : 'WebSearch';
    }
    case 'Task':
    case 'Agent': {
      const d = inputStr(input, 'description', 'subagent_type');
      return d ? `Delegate: ${truncate(d, 70)}` : 'Delegate to subagent';
    }
    case 'TodoWrite': {
      const todos = Array.isArray(input.todos) ? input.todos : [];
      const active = todos.find((t) => isRecord(t) && t.status === 'in_progress');
      const label = isRecord(active) ? inputStr(active, 'activeForm', 'content') : undefined;
      return label ? `Plan: ${truncate(label, 70)}` : `Plan (${todos.length} todos)`;
    }
    default: {
      const short = name.startsWith('mcp__') ? name.split('__').slice(1).join(' ') : name;
      return truncate(short, 60);
    }
  }
}

export interface TranscriptMeta {
  sessionId?: string;
  cwd?: string;
  model?: string;
  gitBranch?: string;
  title?: string;
  ts?: number;
  entryType?: string;
  usage?: { requestKey: string; input: number; output: number };
}

function parseTs(value: unknown): number | undefined {
  const s = str(value);
  if (!s) return undefined;
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : undefined;
}

export function transcriptMeta(entry: unknown): TranscriptMeta {
  if (!isRecord(entry)) return {};
  const meta: TranscriptMeta = {
    sessionId: str(entry.sessionId),
    cwd: str(entry.cwd),
    gitBranch: str(entry.gitBranch),
    ts: parseTs(entry.timestamp),
    entryType: str(entry.type),
  };
  if (entry.type === 'ai-title' || entry.type === 'summary') meta.title = str(entry.aiTitle) ?? str(entry.summary);
  const message = entry.message;
  if (entry.type === 'assistant' && isRecord(message)) {
    const model = str(message.model);
    if (model && model !== '<synthetic>') meta.model = model;
    const usage = message.usage;
    if (isRecord(usage)) {
      const key = str(message.id) ?? str(entry.requestId) ?? str(entry.uuid) ?? '';
      const input =
        (num(usage.input_tokens) ?? 0) + (num(usage.cache_read_input_tokens) ?? 0) + (num(usage.cache_creation_input_tokens) ?? 0);
      meta.usage = { requestKey: key, input, output: num(usage.output_tokens) ?? 0 };
    }
  }
  return meta;
}

/** Map one transcript line to zero or more activities. Never throws. */
export function transcriptEntryToActivities(entry: unknown, cwdHint?: string): ActivityDraft[] {
  try {
    if (!isRecord(entry)) return [];
    const ts = parseTs(entry.timestamp) ?? Date.now();
    const cwd = str(entry.cwd) ?? cwdHint;
    const message = entry.message;
    if (!isRecord(message)) return [];
    const content = message.content;
    const out: ActivityDraft[] = [];

    if (entry.type === 'assistant' && Array.isArray(content)) {
      for (const block of content) {
        if (!isRecord(block)) continue;
        if (block.type === 'tool_use') {
          const name = str(block.name) ?? 'tool';
          out.push({ kind: toolKind(name), text: describeToolUse(name, block.input, cwd), ts });
        } else if (block.type === 'text') {
          const text = str(block.text);
          if (text && text.trim()) out.push({ kind: 'message', text: firstLine(text, 120), detail: truncate(text, 2000), ts });
        } else if (block.type === 'thinking' || block.type === 'redacted_thinking') {
          const text = str(block.thinking);
          out.push({ kind: 'think', text: text && text.trim() ? firstLine(text, 120) : 'Thinking…', ts });
        }
      }
    } else if (entry.type === 'user') {
      if (typeof content === 'string') {
        if (content.trim() && !content.startsWith('<')) out.push({ kind: 'message', text: `Prompt: ${firstLine(content, 100)}`, ts });
      } else if (Array.isArray(content)) {
        for (const block of content) {
          if (!isRecord(block)) continue;
          if (block.type === 'tool_result' && block.is_error === true) {
            const c = block.content;
            const text = typeof c === 'string' ? c : Array.isArray(c) ? c.map((x) => (isRecord(x) ? str(x.text) ?? '' : '')).join(' ') : '';
            out.push({ kind: 'error', text: `Tool error: ${firstLine(text || 'failed', 100)}`, ts });
          } else if (block.type === 'text' && entry.isMeta !== true) {
            const text = str(block.text);
            if (text && text.trim() && !text.startsWith('<')) out.push({ kind: 'message', text: `Prompt: ${firstLine(text, 100)}`, ts });
          }
        }
      }
    }
    return out;
  } catch {
    return [];
  }
}

// ── scanner ───────────────────────────────────────────────────────────────

interface SessionState {
  sessionId: string;
  file: string;
  cwd?: string;
  model?: string;
  gitBranch?: string;
  title?: string;
  lastActivityAt: number;
  lastEntryType?: string;
  countedRequests: Set<string>;
  pending: ActivityDraft[];
  tokensIn: number;
  tokensOut: number;
}

export function claudeConfigDir(env: NodeJS.ProcessEnv = process.env): string {
  return env.CLAUDE_CONFIG_DIR?.trim() || path.join(os.homedir(), '.claude');
}

const BACKFILL_ACTIVITIES = 12;

export class ClaudeCodeScanner {
  private tailer = new JsonlTailer();
  private sessions = new Map<string, SessionState>();

  constructor(private readonly root = path.join(claudeConfigDir(), 'projects')) {}

  async scan(nowMs = Date.now()): Promise<DetectedAgent[]> {
    let projectDirs: string[];
    try {
      projectDirs = await fs.readdir(this.root);
    } catch {
      return [];
    }
    const activeFiles: Array<{ file: string; size: number; mtime: number }> = [];
    for (const dir of projectDirs) {
      const full = path.join(this.root, dir);
      let entries: string[];
      try {
        entries = await fs.readdir(full);
      } catch {
        continue;
      }
      for (const name of entries) {
        if (!name.endsWith('.jsonl')) continue;
        const file = path.join(full, name);
        try {
          const st = await fs.stat(file);
          if (nowMs - st.mtimeMs <= ACTIVE_WINDOW_MS) activeFiles.push({ file, size: st.size, mtime: st.mtimeMs });
        } catch {
          // vanished between readdir and stat
        }
      }
    }

    const seen = new Set<string>();
    for (const { file, size, mtime } of activeFiles) {
      seen.add(file);
      const { lines, firstRead } = await this.tailer.read(file, size);
      const fallbackId = path.basename(file, '.jsonl');
      let session = [...this.sessions.values()].find((s) => s.file === file);
      for (const line of lines) {
        const meta = transcriptMeta(line);
        const sid = meta.sessionId ?? fallbackId;
        if (!session || session.sessionId !== sid) {
          session = this.sessions.get(sid) ?? {
            sessionId: sid,
            file,
            lastActivityAt: 0,
            countedRequests: new Set(),
            pending: [],
            tokensIn: 0,
            tokensOut: 0,
          };
          this.sessions.set(sid, session);
        }
        if (meta.cwd) session.cwd = meta.cwd;
        if (meta.model) session.model = meta.model;
        if (meta.gitBranch) session.gitBranch = meta.gitBranch;
        if (meta.title) session.title = meta.title;
        if (meta.usage && !session.countedRequests.has(meta.usage.requestKey)) {
          session.countedRequests.add(meta.usage.requestKey);
          if (session.countedRequests.size > 500) session.countedRequests.clear();
          session.tokensIn += meta.usage.input;
          session.tokensOut += meta.usage.output;
        }
        if (meta.ts && (meta.entryType === 'assistant' || meta.entryType === 'user')) {
          session.lastActivityAt = Math.max(session.lastActivityAt, meta.ts);
          session.lastEntryType = meta.entryType;
        }
        session.pending.push(...transcriptEntryToActivities(line, session.cwd));
      }
      if (session) {
        if (!session.lastActivityAt) session.lastActivityAt = mtime;
        if (firstRead && session.pending.length > BACKFILL_ACTIVITIES) session.pending = session.pending.slice(-BACKFILL_ACTIVITIES);
      }
    }
    this.tailer.forget(seen);

    const result: DetectedAgent[] = [];
    for (const [sid, s] of this.sessions) {
      if (!seen.has(s.file) || nowMs - s.lastActivityAt > ACTIVE_WINDOW_MS) {
        this.sessions.delete(sid);
        continue;
      }
      // A trailing user entry means the model is now working on it.
      const busy = s.lastEntryType === 'user' ? 'thinking' : 'working';
      result.push({
        id: `claude-code:${sid}`,
        source: 'claude-code',
        status: statusByRecency(s.lastActivityAt, nowMs, busy),
        model: s.model,
        cwd: s.cwd,
        label: s.title,
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
