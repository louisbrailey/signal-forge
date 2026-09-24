// Canvas-sprite name tags and speech bubbles, rendered as crisp pixel text.
import * as THREE from 'three';
import type { AgentStatus, ActivityKind } from '../../shared/protocol';

export const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: '#9aa3ad',
  thinking: '#b98cff',
  working: '#5fd35f',
  waiting: '#f2c84b',
  done: '#4ee6c0',
  error: '#ff5252',
  offline: '#5d6166',
};

const KIND_COLORS: Partial<Record<ActivityKind, string>> = {
  read: '#6aa8ff',
  search: '#6aa8ff',
  edit: '#f2a93b',
  bash: '#ff5a3c',
  web: '#b06bff',
  think: '#c9a8ff',
  delegate: '#f2c83a',
  complete: '#4ee67a',
  error: '#ff4a4a',
  plan: '#f2c83a',
  review: '#5fe8ff',
  message: '#e8e8e8',
  tool: '#9ad0a0',
};

const FONT = `"DejaVu Sans", "Segoe UI", Verdana, Helvetica, Arial, sans-serif`;
const PX = 1 / 34; // world units per texture pixel

let scratch: HTMLCanvasElement | null = null;

/** Draw text as hard-edged pixels (alpha thresholded) so it reads like a pixel font. */
function pixelText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  size: number,
  color: string,
  bold = true,
  shadow: string | null = null,
): number {
  scratch ??= document.createElement('canvas');
  const s = scratch;
  const sctx = s.getContext('2d', { willReadFrequently: true })!;
  sctx.font = `${bold ? 'bold ' : ''}${size}px ${FONT}`;
  const w = Math.ceil(sctx.measureText(text).width) + 2;
  const h = Math.ceil(size * 1.4);
  s.width = Math.max(1, w);
  s.height = h;
  sctx.font = `${bold ? 'bold ' : ''}${size}px ${FONT}`;
  sctx.textBaseline = 'alphabetic';
  sctx.fillStyle = '#fff';
  sctx.fillText(text, 1, Math.round(size * 1.05));
  const img = sctx.getImageData(0, 0, s.width, s.height);
  const d = img.data;
  const out = sctx.createImageData(s.width, s.height);
  const o = out.data;
  const c = parseColor(color);
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] > 110) {
      o[i] = c[0];
      o[i + 1] = c[1];
      o[i + 2] = c[2];
      o[i + 3] = 255;
    }
  }
  sctx.putImageData(out, 0, 0);
  if (shadow) {
    // 1px drop shadow, MC-style
    const sh = document.createElement('canvas');
    sh.width = s.width;
    sh.height = s.height;
    const shx = sh.getContext('2d')!;
    shx.drawImage(s, 0, 0);
    shx.globalCompositeOperation = 'source-in';
    shx.fillStyle = shadow;
    shx.fillRect(0, 0, sh.width, sh.height);
    ctx.drawImage(sh, x + 1, y + 1);
  }
  ctx.drawImage(s, x, y);
  return w;
}

function measure(text: string, size: number, bold = true): number {
  scratch ??= document.createElement('canvas');
  const sctx = scratch.getContext('2d', { willReadFrequently: true })!;
  sctx.font = `${bold ? 'bold ' : ''}${size}px ${FONT}`;
  return Math.ceil(sctx.measureText(text).width) + 2;
}

function parseColor(c: string): [number, number, number] {
  const s = c.replace('#', '');
  const n = parseInt(s.length === 3 ? s.split('').map((x) => x + x).join('') : s, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function truncate(text: string, size: number, maxW: number, bold = true): string {
  if (measure(text, size, bold) <= maxW) return text;
  let t = text;
  while (t.length > 1 && measure(t + '…', size, bold) > maxW) t = t.slice(0, -1);
  return t + '…';
}

function spriteFrom(canvas: HTMLCanvasElement): THREE.Sprite {
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false, fog: false });
  const sp = new THREE.Sprite(mat);
  sp.renderOrder = 20;
  sp.userData.baseW = canvas.width * PX;
  sp.userData.baseH = canvas.height * PX;
  sp.scale.set(canvas.width * PX, canvas.height * PX, 1);
  return sp;
}

function replaceTexture(sp: THREE.Sprite, canvas: HTMLCanvasElement): void {
  const mat = sp.material;
  mat.map?.dispose();
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  mat.map = tex;
  mat.needsUpdate = true;
  sp.userData.baseW = canvas.width * PX;
  sp.userData.baseH = canvas.height * PX;
}

export interface TagInfo {
  name: string;
  subtitle: string;
  status: AgentStatus;
  selected: boolean;
  hovered: boolean;
  council: boolean;
}

export class NameTag {
  readonly sprite: THREE.Sprite;
  private key = '';

  constructor(info: TagInfo) {
    this.sprite = spriteFrom(this.draw(info));
    this.key = JSON.stringify(info);
    this.sprite.center.set(0.5, 0);
  }

  update(info: TagInfo): void {
    const k = JSON.stringify(info);
    if (k === this.key) return;
    this.key = k;
    replaceTexture(this.sprite, this.draw(info));
  }

  private draw(info: TagInfo): HTMLCanvasElement {
    const nameSize = 13;
    const subSize = 10;
    const name = truncate(info.name, nameSize, 150);
    const sub = truncate(info.subtitle, subSize, 170, false);
    const dot = 6;
    const w1 = measure(name, nameSize) + dot + 4 + (info.council ? 10 : 0);
    const w2 = sub ? measure(sub, subSize, false) : 0;
    const pad = 4;
    const W = Math.max(w1, w2) + pad * 2;
    const H = pad * 2 + 15 + (sub ? 12 : 0);
    const c = document.createElement('canvas');
    c.width = W;
    c.height = H;
    const ctx = c.getContext('2d')!;
    ctx.imageSmoothingEnabled = false;
    const hl = info.selected || info.hovered;
    ctx.fillStyle = info.selected ? 'rgba(24,18,6,0.78)' : hl ? 'rgba(10,10,10,0.66)' : 'rgba(0,0,0,0.5)';
    ctx.fillRect(1, 0, W - 2, H);
    ctx.fillRect(0, 1, W, H - 2);
    if (info.selected) {
      ctx.fillStyle = '#f2c83a';
      ctx.fillRect(1, 0, W - 2, 1);
      ctx.fillRect(1, H - 1, W - 2, 1);
      ctx.fillRect(0, 1, 1, H - 2);
      ctx.fillRect(W - 1, 1, 1, H - 2);
    }
    let x = Math.round((W - w1) / 2);
    // status dot
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(x + 1, pad + 5, dot, dot);
    ctx.fillStyle = STATUS_COLORS[info.status];
    ctx.fillRect(x, pad + 4, dot, dot);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.fillRect(x, pad + 4, 2, 2);
    x += dot + 4;
    if (info.council) {
      // tiny crown glyph
      ctx.fillStyle = '#f2c83a';
      ctx.fillRect(x, pad + 7, 7, 3);
      ctx.fillRect(x, pad + 4, 1, 3);
      ctx.fillRect(x + 3, pad + 3, 1, 4);
      ctx.fillRect(x + 6, pad + 4, 1, 3);
      x += 10;
    }
    pixelText(ctx, name, x, pad - 1, nameSize, info.selected ? '#ffe58a' : '#ffffff', true, '#3a3a3a');
    if (sub) pixelText(ctx, sub, Math.round((W - w2) / 2), pad + 14, subSize, hl ? '#e0e0e0' : '#b8b8b8', false);
    return c;
  }

  dispose(): void {
    this.sprite.material.map?.dispose();
    this.sprite.material.dispose();
  }
}

export class SpeechBubble {
  readonly sprite: THREE.Sprite;
  private until = 0;
  private shownAt = 0;

  constructor() {
    this.sprite = spriteFrom(this.draw('…', 'message'));
    this.sprite.center.set(0.5, 0);
    this.sprite.visible = false;
    this.sprite.renderOrder = 21;
  }

  show(text: string, kind: ActivityKind, now: number, duration = 4): void {
    replaceTexture(this.sprite, this.draw(text, kind));
    this.until = now + duration;
    this.shownAt = now;
    this.sprite.visible = true;
  }

  get active(): boolean {
    return this.sprite.visible;
  }

  /** returns scale multiplier for pop-in */
  update(now: number): number {
    if (!this.sprite.visible) return 0;
    const age = now - this.shownAt;
    const left = this.until - now;
    if (left <= 0) {
      this.sprite.visible = false;
      return 0;
    }
    this.sprite.material.opacity = Math.min(1, left / 0.4);
    return age < 0.18 ? 0.6 + (age / 0.18) * 0.4 : 1;
  }

  private draw(text: string, kind: ActivityKind): HTMLCanvasElement {
    const size = 11;
    const maxW = 170;
    const words = text.replace(/\s+/g, ' ').trim().split(' ');
    const lines: string[] = [];
    let cur = '';
    for (const w of words) {
      const t = cur ? cur + ' ' + w : w;
      if (measure(t, size, false) > maxW && cur) {
        lines.push(cur);
        cur = w;
        if (lines.length === 2) break;
      } else cur = t;
    }
    if (lines.length < 2 && cur) lines.push(cur);
    if (lines.length === 2 && words.join(' ').length > lines.join(' ').length + 1) lines[1] = truncate(lines[1] + ' …', size, maxW, false);
    lines[0] = truncate(lines[0] ?? '', size, maxW, false);
    const icon = 7;
    const tw = Math.max(...lines.map((l) => measure(l, size, false)));
    const W = tw + icon + 14;
    const lh = 13;
    const H = lines.length * lh + 9 + 5; // + tail
    const c = document.createElement('canvas');
    c.width = W;
    c.height = H;
    const ctx = c.getContext('2d')!;
    const bh = H - 5;
    ctx.fillStyle = '#2b2b2b';
    ctx.fillRect(1, 0, W - 2, bh);
    ctx.fillRect(0, 1, W, bh - 2);
    ctx.fillStyle = '#fbf7ea';
    ctx.fillRect(1, 1, W - 2, bh - 2);
    ctx.fillStyle = '#e4dcc4';
    ctx.fillRect(1, bh - 2, W - 2, 1);
    // tail
    const tx = Math.floor(W / 2) - 3;
    ctx.fillStyle = '#2b2b2b';
    ctx.fillRect(tx, bh - 1, 7, 2);
    ctx.fillRect(tx + 1, bh + 1, 5, 2);
    ctx.fillRect(tx + 2, bh + 3, 3, 2);
    ctx.fillStyle = '#fbf7ea';
    ctx.fillRect(tx + 1, bh - 1, 5, 1);
    ctx.fillStyle = '#e4dcc4';
    ctx.fillRect(tx + 1, bh - 1, 5, 1);
    ctx.fillRect(tx + 2, bh, 3, 2);
    ctx.fillRect(tx + 3, bh + 2, 1, 2);
    // kind icon
    ctx.fillStyle = KIND_COLORS[kind] ?? '#9aa3ad';
    ctx.fillRect(5, 5, icon, icon);
    ctx.fillStyle = 'rgba(0,0,0,0.25)';
    ctx.fillRect(5, 5 + icon - 2, icon, 2);
    lines.forEach((l, i) => pixelText(ctx, l, 5 + icon + 4, 2 + i * lh, size, '#262626', false));
    return c;
  }

  dispose(): void {
    this.sprite.material.map?.dispose();
    this.sprite.material.dispose();
  }
}
