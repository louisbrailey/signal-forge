// Demo population: simulated citizens (live:false) so the world is alive out of the box.
import type { ActivityKind, AgentSource, AgentStatus } from '../shared/protocol.ts';
import { makeAgent } from './agents.ts';
import type { OverrideStore } from './config.ts';
import type { Realm } from './state.ts';

interface Citizen {
  id: string;
  source: AgentSource;
  project: string;
  model?: string;
}

const CITIZENS: Citizen[] = [
  { id: 'demo:1', source: 'claude-code', project: 'signal-forge', model: 'claude-opus-5' },
  { id: 'demo:2', source: 'codex', project: 'tradepilot', model: 'gpt-5-codex' },
  { id: 'demo:3', source: 'gemini-cli', project: 'website', model: 'gemini-2.5-pro' },
  { id: 'demo:4', source: 'ollama', project: 'hydroponic-garden', model: 'llama3.1:8b' },
  { id: 'demo:5', source: 'aider', project: 'hydroponic-garden', model: 'claude-sonnet-5' },
  { id: 'demo:6', source: 'cursor', project: 'website' },
  { id: 'demo:7', source: 'claude-code', project: 'tradepilot', model: 'claude-sonnet-5' },
];

const FILES: Record<string, string[]> = {
  'signal-forge': ['src/signals/momentum.py', 'src/risk/limits.py', 'tests/test_risk.py', 'README.md', 'docs/ARCHITECTURE.md'],
  tradepilot: ['src/broker/paper.ts', 'src/strategy/rebalance.ts', 'src/api/routes.ts', 'package.json'],
  website: ['src/pages/index.astro', 'src/components/Hero.tsx', 'tailwind.config.js', 'public/robots.txt'],
  'hydroponic-garden': ['firmware/pump.c', 'dashboard/app.py', 'sensors/ph.py', 'config/schedule.yaml'],
};

type Step = { kind: ActivityKind; status: AgentStatus; text: (file: string) => string };

const STEPS: Step[] = [
  { kind: 'read', status: 'working', text: (f) => `Read ${f}` },
  { kind: 'read', status: 'working', text: (f) => `Read ${f}` },
  { kind: 'edit', status: 'working', text: (f) => `Edit ${f}` },
  { kind: 'edit', status: 'working', text: (f) => `Write ${f}` },
  { kind: 'bash', status: 'working', text: () => 'Bash: npm test' },
  { kind: 'bash', status: 'working', text: () => 'Bash: git status' },
  { kind: 'search', status: 'working', text: () => "Grep 'TODO'" },
  { kind: 'search', status: 'working', text: () => 'Glob **/*.ts' },
  { kind: 'web', status: 'working', text: () => "WebSearch 'best practice retry backoff'" },
  { kind: 'think', status: 'thinking', text: () => 'Thinking about the approach…' },
  { kind: 'think', status: 'thinking', text: (f) => `Considering how ${f.split('/').pop()} fits together` },
  { kind: 'plan', status: 'working', text: () => 'Plan: break the change into 3 steps' },
  { kind: 'message', status: 'working', text: () => 'Tests pass — moving on to the next step' },
];

export class DemoPopulation {
  private timers = new Map<string, NodeJS.Timeout>();
  private enabled = false;

  constructor(
    private readonly realm: Realm,
    private readonly overrides?: OverrideStore,
  ) {}

  get isEnabled(): boolean {
    return this.enabled;
  }

  setEnabled(on: boolean): void {
    if (on === this.enabled) return;
    this.enabled = on;
    if (on) this.start();
    else this.stop();
    this.realm.setInfo({ demoPopulation: on });
  }

  private start(): void {
    const count = 5 + Math.floor(Math.random() * 3);
    for (const c of CITIZENS.slice(0, count)) {
      const agent = makeAgent(
        { id: c.id, source: c.source, model: c.model, live: false, controllable: false, project: c.project, cwd: `~/code/${c.project}`, takenNames: this.realm.takenNames() },
        this.overrides,
      );
      this.realm.upsertAgent(agent);
      this.schedule(c);
    }
  }

  private stop(): void {
    for (const t of this.timers.values()) clearTimeout(t);
    this.timers.clear();
    for (const c of CITIZENS) this.realm.retireAgent(c.id, 4000);
  }

  private schedule(c: Citizen): void {
    const timer = setTimeout(() => this.tick(c), 2000 + Math.random() * 4000);
    timer.unref?.();
    this.timers.set(c.id, timer);
  }

  private tick(c: Citizen): void {
    if (!this.enabled || !this.realm.getAgent(c.id)) return;
    if (Math.random() < 0.15) {
      this.realm.patchAgent(c.id, { status: 'idle', currentAction: undefined });
    } else {
      const step = STEPS[Math.floor(Math.random() * STEPS.length)]!;
      const files = FILES[c.project] ?? ['README.md'];
      const file = files[Math.floor(Math.random() * files.length)]!;
      this.realm.patchAgent(c.id, { status: step.status });
      this.realm.pushActivity(c.id, { kind: step.kind, text: step.text(file) });
    }
    this.schedule(c);
  }

  dispose(): void {
    for (const t of this.timers.values()) clearTimeout(t);
    this.timers.clear();
  }
}
