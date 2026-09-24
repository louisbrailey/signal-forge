// Standalone world preview with fake agents — served at /world-preview.html (no server needed).
import type { Activity, ActivityKind, Agent, AgentSource, AgentStatus, HatStyle, Mission, MissionStatus, SkinSpec } from '../../shared/protocol';
import { World, type Place } from './World';

const params = new URLSearchParams(location.search);
const container = document.getElementById('world')!;
const world = new World(container);

function skin(p: Partial<SkinSpec> & { hat: HatStyle }): SkinSpec {
  return {
    skin: '#e0ac7e',
    hair: '#4a2f1b',
    eyes: '#3a6fd8',
    shirt: '#3f7fbf',
    pants: '#2e3f6b',
    shoes: '#3a2a1e',
    accent: '#f2c83a',
    ...p,
  };
}

function agent(id: string, name: string, title: string, role: 'council' | 'worker', source: AgentSource, status: AgentStatus, s: SkinSpec, model?: string): Agent {
  return {
    id,
    name,
    title,
    role,
    source,
    model,
    status,
    live: false,
    controllable: role === 'worker',
    skin: s,
    project: 'signal-forge',
    lastActivityAt: Date.now(),
    createdAt: Date.now(),
    stats: { toolCalls: Math.floor(Math.random() * 50), tasksDone: 0, tokensIn: 0, tokensOut: 0 },
    recent: [],
  };
}

const agents: Agent[] = [
  agent('api:council-a', 'Aurelia', 'High Architect', 'council', 'api', 'thinking', skin({ hat: 'crown', skin: '#f1c9a5', hair: '#e8d27a', shirt: '#6a2fa0', pants: '#3a1a5a', accent: '#f2c83a', cape: '#8a2a2a', eyes: '#2a8a5a' }), 'claude-opus'),
  agent('api:council-b', 'Merrow', 'Sage of Plans', 'council', 'api', 'idle', skin({ hat: 'wizard', skin: '#c68a5e', hair: '#d8d8d8', shirt: '#2a3f8a', pants: '#1a2550', accent: '#8fd0ff', cape: '#1f2f6a', eyes: '#6a3a1a' }), 'gpt-5'),
  agent('api:council-c', 'Sable', 'Keeper of Lore', 'council', 'api', 'working', skin({ hat: 'hood', skin: '#8a5a3a', hair: '#1a1a1a', shirt: '#2f5a3a', pants: '#1f3a28', accent: '#e0b040', cape: '#3a6a3a', eyes: '#3a2a1a' }), 'gemini-pro'),
  agent('claude-code:1', 'Ember', 'Claude Code · signal-forge', 'worker', 'claude-code', 'working', skin({ hat: 'cap', shirt: '#d8743a', pants: '#3a3a4a', accent: '#f2e0b0', hair: '#8a3a1a' }), 'sonnet'),
  agent('codex:2', 'Flint', 'Codex · api', 'worker', 'codex', 'thinking', skin({ hat: 'helmet', skin: '#d8a070', shirt: '#5a5a62', pants: '#2a2a30', accent: '#c02a2a', hair: '#2a1a0a' }), 'codex'),
  agent('gemini:3', 'Wren', 'Gemini CLI · docs', 'worker', 'gemini-cli', 'idle', skin({ hat: 'headband', skin: '#f0d0b0', hair: '#c05a2a', shirt: '#3aa0a0', pants: '#2a4a6a', accent: '#ff6a8a', eyes: '#2a6a2a' }), 'gemini-flash'),
  agent('aider:4', 'Bram', 'Aider · tools', 'worker', 'aider', 'waiting', skin({ hat: 'none', skin: '#a0704a', hair: '#1a120a', shirt: '#7a8a3a', pants: '#4a3a2a', accent: '#d8b060' }), 'deepseek'),
  agent('ollama:5', 'Pip', 'Ollama · local', 'worker', 'ollama', 'done', skin({ hat: 'cap', skin: '#f5d6c0', hair: '#f0e080', shirt: '#e05a7a', pants: '#5a3a6a', accent: '#ffffff' }), 'llama3'),
  agent('cursor:6', 'Quill', 'Cursor · web', 'worker', 'cursor', 'working', skin({ hat: 'none', skin: '#6a4028', hair: '#0a0a0a', shirt: '#f0f0f0', pants: '#2a2a2a', accent: '#3a7aff' }), 'composer'),
  agent('copilot:7', 'Moss', 'Copilot · infra', 'worker', 'copilot', 'error', skin({ hat: 'helmet', skin: '#e8b890', hair: '#5a3a1a', shirt: '#3a6a3a', pants: '#3a3020', accent: '#f0a020' }), 'gpt-4.1'),
  agent('demo:8', 'Juniper', 'Demo citizen', 'worker', 'demo', 'idle', skin({ hat: 'headband', skin: '#d09a70', hair: '#3a2010', shirt: '#9a5ad0', pants: '#3a2a5a', accent: '#ffd040' }), 'haiku'),
];

world.setAgents(agents);
(window as unknown as { world: World }).world = world;

world.onSelect = (id) => {
  world.setSelected(id);
  if (id) world.focusAgent(id);
};
world.onHover = () => {};

const place = params.get('place') as Place | null;
if (place) world.focusPlace(place, params.has('instant'));
const time = params.get('time');
if (time === 'day' || time === 'night' || time === 'auto') world.setTimeMode(time);
else world.setTimeMode('day');
if (params.get('quality') === 'low') world.setQuality('low');
const sel = params.get('select');
if (sel) {
  world.setSelected(sel);
  world.focusAgent(sel);
}
(window as unknown as { dbg: () => unknown }).dbg = () => (world as unknown as { renderer: { info: unknown } }).renderer.info;

// ---- simulated activity
const texts: Record<ActivityKind, string[]> = {
  read: ['Read server/index.ts', 'Read README.md', 'Read shared/protocol.ts'],
  edit: ['Edit src/world/World.ts', 'Edit package.json', 'Write tests/realm.test.ts'],
  bash: ['npm test', 'git status', 'tsc --noEmit'],
  search: ['Grep "onActivity"', 'Glob src/**/*.ts'],
  web: ['Fetch three.js docs', 'Search: voxel AO'],
  tool: ['Run formatter'],
  think: ['Considering the trade-offs…'],
  message: ['On it!', 'Done soon'],
  plan: ['Plan: 3 milestones'],
  delegate: ['Delegating the API work'],
  review: ['Reviewing Flint’s patch'],
  complete: ['Task complete!'],
  error: ['Tests failed (2)'],
  system: ['…'],
};
const workerKinds: ActivityKind[] = ['edit', 'edit', 'edit', 'read', 'bash', 'search', 'web', 'think', 'complete', 'error', 'message'];
const councilKinds: ActivityKind[] = ['think', 'plan', 'delegate', 'review', 'message'];
let n = 0;
const pick = <T,>(xs: T[]): T => xs[Math.floor(Math.random() * xs.length)];
function emit(a: Agent, kind: ActivityKind): void {
  const act: Activity = { id: `p${n++}`, agentId: a.id, ts: Date.now(), kind, text: pick(texts[kind]) };
  world.onActivity(act);
}

if (!params.has('still')) {
  setInterval(() => {
    const a = pick(agents);
    emit(a, pick(a.role === 'council' ? councilKinds : workerKinds));
  }, 900);
  setInterval(() => {
    const c = pick(agents.filter((a) => a.role === 'council'));
    const w = pick(agents.filter((a) => a.role === 'worker'));
    if (Math.random() < 0.6) world.delegate(c.id, w.id);
    else world.deliver(w.id, c.id);
  }, 3500);
  const statuses: AgentStatus[] = ['idle', 'thinking', 'working', 'waiting', 'done', 'working', 'working'];
  setInterval(() => {
    const a = pick(agents);
    a.status = pick(statuses);
    world.setAgents(agents.map((x) => ({ ...x })));
  }, 5000);
}

const missionCycle: (MissionStatus | null)[] = ['deliberating', 'planning', 'executing', 'reviewing', null];
let mi = 0;
const setM = (): void => {
  const st = missionCycle[mi++ % missionCycle.length];
  const m: Mission | null = st
    ? { id: 'm1', goal: 'Build the realm', status: st, simulated: true, createdAt: Date.now(), updatedAt: Date.now(), taskIds: [], transcript: [] }
    : null;
  world.setMission(m);
};
setM();
if (!params.has('still')) setInterval(setM, 8000);

// burst of initial activity so screenshots have something going on
setTimeout(() => {
  emit(agents[3], 'edit');
  emit(agents[5], 'read');
  emit(agents[0], 'think');
  emit(agents[8], 'bash');
  world.delegate(agents[1].id, agents[4].id);
}, 1500);
setTimeout(() => {
  emit(agents[7], 'complete');
  emit(agents[2], 'plan');
}, 3500);

// debug camera: ?cam=px,py,pz,tx,ty,tz
const camParam = params.get('cam');
if (camParam) {
  const v = camParam.split(',').map(Number);
  const rig = (world as unknown as { rig: { set: (p: { x: number; y: number; z: number }, t: { x: number; y: number; z: number }) => void } }).rig;
  rig.set({ x: v[0], y: v[1], z: v[2] }, { x: v[3], y: v[4], z: v[5] });
}

// ?fx: fire one of every effect shortly after load (for visual checks)
if (params.has('fx')) {
  setTimeout(() => {
    emit(agents[7], 'complete');
    emit(agents[3], 'bash');
    emit(agents[5], 'web');
    emit(agents[9], 'error');
    emit(agents[4], 'read');
    emit(agents[8], 'edit');
    emit(agents[0], 'delegate');
    world.delegate(agents[0].id, agents[3].id);
    world.delegate(agents[1].id, agents[8].id);
    world.deliver(agents[6].id, agents[2].id);
    // fast-forward the simulation so slow (software-GL) screenshots catch effects mid-flight
    const ff = Number(params.get('ff') ?? '0.9');
    const step = (world as unknown as { step: (dt: number) => void }).step.bind(world);
    for (let t = 0; t < ff; t += 1 / 30) step(1 / 30);
  }, 2500);
}
