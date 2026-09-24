import type { ActivityKind, Agent, AgentStatus, SkinSpec } from '../../shared/protocol';

export function esc(s: unknown): string {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, cls = '', html = ''): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (html) el.innerHTML = html;
  return el;
}

export function ago(ts: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 5) return 'now';
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const hr = Math.round(m / 60);
  return hr < 48 ? `${hr}h` : `${Math.round(hr / 24)}d`;
}

export function clock(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function compact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1e6) return `${(n / 1000).toFixed(n < 1e4 ? 1 : 0)}k`;
  return `${(n / 1e6).toFixed(1)}M`;
}

export const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: 'Idle',
  thinking: 'Thinking',
  working: 'Working',
  waiting: 'Waiting',
  done: 'Done',
  error: 'Error',
  offline: 'Left the realm',
};

export function statusDot(s: AgentStatus): string {
  const pulse = s === 'working' || s === 'thinking' ? ' pulse' : '';
  return `<i class="dot s-${s}${pulse}" title="${STATUS_LABEL[s]}"></i>`;
}

export const KIND_ICON: Record<ActivityKind, string> = {
  read: '📖', edit: '⛏', bash: '⚡', search: '🔍', web: '🧭', tool: '🔧', think: '💭', message: '💬',
  plan: '🗺', delegate: '📜', review: '⚖', complete: '✦', error: '✖', system: '◆',
};

export const SOURCE_LABEL: Record<Agent['source'], string> = {
  'claude-code': 'Claude Code', codex: 'Codex CLI', 'gemini-cli': 'Gemini CLI', aider: 'Aider', cursor: 'Cursor',
  ollama: 'Ollama', copilot: 'Copilot CLI', opencode: 'opencode', goose: 'Goose', api: 'Claude API', demo: 'Demo', other: 'Agent',
};

/** Friendly short label for a model id: "claude-opus-5-5" → "Opus 5.5". */
export function modelLabel(model?: string): string {
  if (!model) return '';
  const m = model.match(/^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$/);
  if (m) return `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? `.${m[3]}` : ''}`;
  return model.length > 28 ? `${model.slice(0, 27)}…` : model;
}

// ---- pixel head avatars, drawn from the same SkinSpec the 3D villagers use ----
const headCache = new Map<string, string>();

export function headURL(skin: SkinSpec): string {
  const key = JSON.stringify(skin);
  const hit = headCache.get(key);
  if (hit) return hit;
  const c = document.createElement('canvas');
  c.width = c.height = 8;
  const g = c.getContext('2d')!;
  const px = (x: number, y: number, col: string) => { g.fillStyle = col; g.fillRect(x, y, 1, 1); };
  g.fillStyle = skin.skin;
  g.fillRect(0, 0, 8, 8);
  // hair: top two rows + temples
  g.fillStyle = skin.hair;
  g.fillRect(0, 0, 8, 2);
  px(0, 2, skin.hair); px(7, 2, skin.hair); px(0, 3, skin.hair); px(7, 3, skin.hair);
  // eyes (white + iris), brows, nose shade, mouth
  px(1, 4, '#ffffff'); px(2, 4, skin.eyes); px(5, 4, skin.eyes); px(6, 4, '#ffffff');
  px(1, 3, shade(skin.hair, -0.1)); px(2, 3, shade(skin.hair, -0.1)); px(5, 3, shade(skin.hair, -0.1)); px(6, 3, shade(skin.hair, -0.1));
  px(3, 5, shade(skin.skin, -0.12)); px(4, 5, shade(skin.skin, -0.12));
  px(3, 6, shade(skin.skin, -0.3)); px(4, 6, shade(skin.skin, -0.3));
  g.fillStyle = shade(skin.skin, -0.08);
  g.fillRect(0, 7, 8, 1);
  switch (skin.hat) {
    case 'crown':
      g.fillStyle = '#f5c542'; g.fillRect(0, 0, 8, 1);
      px(0, 0, '#f5c542'); px(1, 1, '#d9a520'); px(6, 1, '#d9a520');
      px(3, 0, '#e03a3a'); px(4, 0, '#3ad1e0');
      break;
    case 'wizard': g.fillStyle = skin.accent; g.fillRect(0, 0, 8, 2); px(3, 0, '#f5c542'); break;
    case 'hood': g.fillStyle = skin.shirt; g.fillRect(0, 0, 8, 2); g.fillRect(0, 2, 1, 5); g.fillRect(7, 2, 1, 5); break;
    case 'helmet': g.fillStyle = '#c9ced8'; g.fillRect(0, 0, 8, 2); px(0, 2, '#9aa1ae'); px(7, 2, '#9aa1ae'); break;
    case 'cap': g.fillStyle = skin.accent; g.fillRect(0, 0, 8, 2); g.fillRect(0, 2, 5, 1); break;
    case 'headband': g.fillStyle = skin.accent; g.fillRect(0, 2, 8, 1); break;
    default: break;
  }
  const url = c.toDataURL();
  headCache.set(key, url);
  return url;
}

export function headImg(skin: SkinSpec, cls = ''): string {
  return `<img class="head ${cls}" src="${headURL(skin)}" alt="" draggable="false" />`;
}

function shade(hex: string, amt: number): string {
  const n = parseInt(hex.replace('#', ''), 16);
  if (Number.isNaN(n)) return hex;
  const f = (v: number) => Math.max(0, Math.min(255, Math.round(v + 255 * amt)));
  const r = f((n >> 16) & 255), gg = f((n >> 8) & 255), b = f(n & 255);
  return `#${((r << 16) | (gg << 8) | b).toString(16).padStart(6, '0')}`;
}

// ---- tiny, safe markdown (escape first, then a handful of block/inline rules) ----
export function md(src: string): string {
  const out: string[] = [];
  const lines = esc(src).split('\n');
  let list: 'ul' | 'ol' | null = null;
  let para: string[] = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('```')) {
      flushPara(); closeList();
      const body: string[] = [];
      while (++i < lines.length && !lines[i].startsWith('```')) body.push(lines[i]);
      out.push(`<pre><code>${body.join('\n')}</code></pre>`);
      continue;
    }
    const hm = line.match(/^(#{1,4})\s+(.*)$/);
    if (hm) { flushPara(); closeList(); out.push(`<h${hm[1].length}>${inline(hm[2])}</h${hm[1].length}>`); continue; }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const want = ul ? 'ul' : 'ol';
      if (list !== want) { closeList(); out.push(`<${want}>`); list = want; }
      out.push(`<li>${inline((ul ?? ol)![1])}</li>`);
      continue;
    }
    if (!line.trim()) { flushPara(); closeList(); continue; }
    closeList();
    para.push(line);
  }
  flushPara(); closeList();
  return out.join('');
}

function inline(s: string): string {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/(^|\s)_([^_]+)_(?=\s|$|[.,;:!?])/g, '$1<em>$2</em>');
}
