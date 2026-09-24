import type { Agent, AgentRole, AgentSource, HatStyle, SkinSpec } from '../shared/protocol.ts';
import { hash32, pick, seededRandom } from './util.ts';

const NAMES = [
  'Ember', 'Flint', 'Mossa', 'Quill', 'Rune', 'Sable', 'Tinder', 'Wren', 'Cobble', 'Birch', 'Lapis', 'Redstone',
  'Ashby', 'Bramble', 'Cinder', 'Dusk', 'Fern', 'Gravel', 'Hazel', 'Ingot', 'Juniper', 'Kelp', 'Loam', 'Marrow',
  'Nettle', 'Obsidian', 'Pebble', 'Quartz', 'Rowan', 'Slate', 'Thistle', 'Umber', 'Vale', 'Willow', 'Yarrow',
  'Alder', 'Basalt', 'Clover', 'Dune', 'Elder', 'Fable', 'Glint', 'Heath', 'Ivy', 'Jasper', 'Kindle', 'Lichen',
  'Moss', 'Nimbus', 'Onyx', 'Pike', 'Reed', 'Sorrel', 'Tallow', 'Warden', 'Zephyr', 'Copper', 'Amber', 'Tuff',
  'Calcite', 'Mica', 'Sprout', 'Bellow', 'Cress', 'Oaken', 'Prism', 'Shale', 'Torch', 'Wick', 'Bastion',
];

const SKIN_TONES = ['#f4d0b0', '#e8b894', '#d49a6a', '#b87a4b', '#8d5a3b', '#6b4029', '#f0c8a0', '#c68a5a'];
const HAIR = ['#2b1d14', '#4a2f1b', '#6b4423', '#a0692e', '#d9b45a', '#e8d7a8', '#7a2e1c', '#1f1f24', '#8a8a8a', '#c9c2b8'];
const EYES = ['#2d4a8a', '#3a6b35', '#5b3a1e', '#1e1e28', '#4a7a8c', '#6a4a8a', '#2f5d50'];
const PANTS = ['#3b3f5c', '#4a3b2a', '#2f3b2f', '#3a3a3a', '#5a4632', '#2c3a4f'];
const SHOES = ['#2a211a', '#3b2e24', '#1e1e1e', '#4a3a2c'];

interface Theme {
  shirts: readonly string[];
  accents: readonly string[];
  hats: readonly HatStyle[];
}

const SOURCE_THEMES: Record<AgentSource, Theme> = {
  'claude-code': { shirts: ['#c96442', '#d97757', '#b85a3a', '#e08a5f'], accents: ['#f3d9c4', '#7a3522'], hats: ['none', 'headband', 'cap'] },
  codex: { shirts: ['#10a37f', '#1a8f7a', '#2bb58f', '#0e7c66'], accents: ['#d4f5ea', '#0a4f40'], hats: ['none', 'cap', 'hood'] },
  'gemini-cli': { shirts: ['#4b6fe0', '#6a5ae0', '#5b7cfa', '#7b61d9'], accents: ['#e3e0ff', '#2b2f8a'], hats: ['none', 'hood', 'headband'] },
  ollama: { shirts: ['#f2efe6', '#e9e2d0', '#fbf8f0', '#ddd6c4'], accents: ['#8a7f6a', '#3a3a3a'], hats: ['none', 'hood'] },
  aider: { shirts: ['#e6c229', '#f2d24b', '#d9a91a', '#f5c542'], accents: ['#4a3a0a', '#fff4c2'], hats: ['none', 'cap', 'helmet'] },
  cursor: { shirts: ['#2e2e33', '#3a3a40', '#26262a', '#45454d'], accents: ['#c0c4cc', '#e5e7eb'], hats: ['none', 'headband', 'hood'] },
  copilot: { shirts: ['#4338ca', '#4f46e5', '#3730a3', '#5b50e8'], accents: ['#c7d2fe', '#1e1b4b'], hats: ['none', 'helmet', 'cap'] },
  opencode: { shirts: ['#e2703a', '#3aa0e2', '#8ae23a', '#e23a8a'], accents: ['#1f1f1f', '#f5f5f5'], hats: ['none', 'cap', 'headband'] },
  goose: { shirts: ['#9aa5b1', '#6b7c8f', '#b0a07a', '#7a9a6b'], accents: ['#2d2d2d', '#f0e6d2'], hats: ['none', 'hood', 'cap'] },
  api: { shirts: ['#5aa9e6', '#4a9ad6'], accents: ['#e6f3fc', '#1d4e75'], hats: ['none', 'cap'] },
  demo: { shirts: ['#8b6fb0', '#6fb08b', '#b08b6f'], accents: ['#f0f0f0', '#303030'], hats: ['none', 'cap'] },
  other: { shirts: ['#8c6e54', '#6e8c54', '#546e8c', '#8c546e'], accents: ['#e8e0d0', '#2a2a2a'], hats: ['none', 'cap', 'hood'] },
};

const MODEL_THEMES: Array<{ match: RegExp; theme: Theme }> = [
  { match: /sonnet/i, theme: { shirts: ['#5aa9e6', '#6cb8f0', '#4a9ad6'], accents: ['#e6f3fc', '#1d4e75'], hats: ['cap', 'none'] } },
  { match: /haiku/i, theme: { shirts: ['#7fd8b6', '#6ccfa6', '#94e2c4'], accents: ['#e8fbf3', '#1f5e48'], hats: ['headband', 'none'] } },
];

const COUNCIL_ROBES = ['#5b2a86', '#7a1f3d', '#3b2a6b', '#6b1f5b'];
const COUNCIL_CAPES = ['#8e1b2c', '#4b1d7a', '#b8860b', '#6a1a4c'];
const COUNCIL_ACCENTS = ['#d4af37', '#f0c75e', '#e5c07b'];

/** Deterministic name for an id; probes forward past names in `taken` so villagers stay distinct. */
export function nameFor(id: string, taken?: ReadonlySet<string>): string {
  const start = hash32(id) % NAMES.length;
  for (let i = 0; i < NAMES.length; i++) {
    const name = NAMES[(start + i) % NAMES.length]!;
    if (!taken?.has(name)) return name;
  }
  return NAMES[start]!;
}

export interface IdentityInput {
  id: string;
  source: AgentSource;
  role: AgentRole;
  model?: string;
  /** Council chair gets the crown. */
  chair?: boolean;
}

export function skinFor(input: IdentityInput): SkinSpec {
  const rand = seededRandom(input.id);
  const base = {
    skin: pick(SKIN_TONES, rand),
    hair: pick(HAIR, rand),
    eyes: pick(EYES, rand),
    pants: pick(PANTS, rand),
    shoes: pick(SHOES, rand),
  };
  if (input.role === 'council') {
    return {
      ...base,
      shirt: pick(COUNCIL_ROBES, rand),
      accent: pick(COUNCIL_ACCENTS, rand),
      hat: input.chair ? 'crown' : 'wizard',
      cape: pick(COUNCIL_CAPES, rand),
    };
  }
  const modelTheme = input.source === 'api' && input.model ? MODEL_THEMES.find((m) => m.match.test(input.model!))?.theme : undefined;
  const theme = modelTheme ?? SOURCE_THEMES[input.source] ?? SOURCE_THEMES.other;
  return { ...base, shirt: pick(theme.shirts, rand), accent: pick(theme.accents, rand), hat: pick(theme.hats, rand) };
}

const SOURCE_LABELS: Record<AgentSource, string> = {
  'claude-code': 'Claude Code',
  codex: 'Codex',
  'gemini-cli': 'Gemini CLI',
  aider: 'Aider',
  cursor: 'Cursor',
  ollama: 'Ollama',
  copilot: 'Copilot',
  opencode: 'opencode',
  goose: 'Goose',
  api: 'Claude API',
  demo: 'Demo',
  other: 'Agent',
};

export function sourceLabel(source: AgentSource): string {
  return SOURCE_LABELS[source] ?? 'Agent';
}

/** "claude-sonnet-5" → "Sonnet 5"; unknown ids pass through. */
export function modelLabel(model: string): string {
  const m = /claude-([a-z]+)-(\d+)(?:-(\d+))?/.exec(model);
  if (!m) return model;
  const family = m[1]!.charAt(0).toUpperCase() + m[1]!.slice(1);
  return m[3] && m[3].length <= 2 ? `${family} ${m[2]}.${m[3]}` : `${family} ${m[2]}`;
}

export function titleFor(agent: Pick<Agent, 'source' | 'role' | 'model' | 'project' | 'live'>): string {
  if (agent.source === 'api') {
    const label = agent.model ? modelLabel(agent.model) : 'Claude';
    return agent.role === 'council' ? `Councillor · ${label}` : `${label} · Worker`;
  }
  const base = sourceLabel(agent.source);
  const demo = agent.live ? '' : ' (demo)';
  if (agent.source === 'ollama' && agent.model) return `Ollama · ${agent.model}${demo}`;
  const suffix = agent.project ? ` · ${agent.project}` : '';
  return `${base}${suffix}${demo}`;
}
