import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import type { AgentRole } from '../shared/protocol.ts';
import { isRecord } from './util.ts';

export const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export interface CouncilSeat {
  model: string;
  title: string;
}

export interface RealmConfig {
  council: CouncilSeat[];
  workers: string[];
  apiKeyPresent: boolean;
}

const DEFAULT_TITLES = ['High Architect', 'Grand Strategist', 'Warden'];
const EXTRA_TITLES = ['Loremaster', 'Seer', 'Keeper of Scrolls', 'Oracle'];

export const DEFAULT_COUNCIL_MODELS = ['claude-fable-5-1', 'claude-opus-5-5', 'claude-opus-5'];
export const DEFAULT_WORKER_MODELS = ['claude-sonnet-5', 'claude-sonnet-5', 'claude-haiku-4-5', 'claude-haiku-4-5'];

const seatSchema = z.union([z.string().min(1), z.object({ model: z.string().min(1), title: z.string().min(1).optional() })]);
const fileSchema = z.object({
  councilModels: z.array(seatSchema).min(1).optional(),
  workerModels: z.array(z.string().min(1)).optional(),
});

function readJson(file: string): unknown {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return undefined;
  }
}

function parseList(value: string | undefined): string[] | undefined {
  if (!value) return undefined;
  const list = value.split(',').map((s) => s.trim()).filter(Boolean);
  return list.length ? list : undefined;
}

export function seatTitle(index: number): string {
  return DEFAULT_TITLES[index] ?? EXTRA_TITLES[(index - DEFAULT_TITLES.length) % EXTRA_TITLES.length]!;
}

export function hasApiKey(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(env.ANTHROPIC_API_KEY?.trim() || env.ANTHROPIC_AUTH_TOKEN?.trim());
}

export function loadConfig(root = PROJECT_ROOT, env: NodeJS.ProcessEnv = process.env): RealmConfig {
  let council: CouncilSeat[] = DEFAULT_COUNCIL_MODELS.map((model, i) => ({ model, title: seatTitle(i) }));
  let workers = [...DEFAULT_WORKER_MODELS];

  for (const name of ['realm.config.json', 'realm.config.local.json']) {
    const parsed = fileSchema.safeParse(readJson(path.join(root, name)));
    if (!parsed.success) continue;
    if (parsed.data.councilModels) {
      council = parsed.data.councilModels.map((seat, i) =>
        typeof seat === 'string' ? { model: seat, title: seatTitle(i) } : { model: seat.model, title: seat.title ?? seatTitle(i) },
      );
    }
    if (parsed.data.workerModels) workers = parsed.data.workerModels;
  }

  const envCouncil = parseList(env.REALM_COUNCIL_MODELS);
  if (envCouncil) council = envCouncil.map((model, i) => ({ model, title: seatTitle(i) }));
  workers = parseList(env.REALM_WORKER_MODELS) ?? workers;

  return { council, workers, apiKeyPresent: hasApiKey(env) };
}

// ── per-agent overrides (role / name), persisted in ~/.agent-realm ─────────

export interface AgentOverride {
  role?: AgentRole;
  name?: string;
}

export class OverrideStore {
  private data: Record<string, AgentOverride> = {};
  private saveTimer?: NodeJS.Timeout;
  private dirty = false;

  constructor(private readonly file: string | null = path.join(os.homedir(), '.agent-realm', 'overrides.json')) {
    if (!file) return;
    const raw = readJson(file);
    if (isRecord(raw) && isRecord(raw.agents)) {
      for (const [id, value] of Object.entries(raw.agents)) {
        if (!isRecord(value)) continue;
        const o: AgentOverride = {};
        if (value.role === 'council' || value.role === 'worker') o.role = value.role;
        if (typeof value.name === 'string' && value.name.trim()) o.name = value.name.trim().slice(0, 32);
        this.data[id] = o;
      }
    }
  }

  get(id: string): AgentOverride {
    return this.data[id] ?? {};
  }

  set(id: string, patch: AgentOverride): void {
    this.data[id] = { ...this.data[id], ...patch };
    this.dirty = true;
    this.scheduleSave();
  }

  private scheduleSave(): void {
    if (!this.file || this.saveTimer) return;
    this.saveTimer = setTimeout(() => {
      this.saveTimer = undefined;
      this.flush();
    }, 300);
    this.saveTimer.unref?.();
  }

  flush(): void {
    if (!this.file || !this.dirty) return;
    this.dirty = false;
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      fs.writeFileSync(this.file, JSON.stringify({ agents: this.data }, null, 2));
    } catch {
      // Overrides are a convenience; failing to persist must not crash the realm.
    }
  }
}
