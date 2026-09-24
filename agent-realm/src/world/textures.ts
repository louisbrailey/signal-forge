// Procedural pixel-art textures: block atlas, villager skins, and small sprite canvases.
// Everything is drawn in code; no external image assets.
import * as THREE from 'three';
import { T } from './blocks';
import { hashString, rng } from './noise';
import type { SkinSpec } from '../../shared/protocol';

export type RGB = [number, number, number];

export function hex(c: string): RGB {
  let s = c.trim().replace('#', '');
  if (s.length === 3) s = s.split('').map((ch) => ch + ch).join('');
  const n = parseInt(s.slice(0, 6), 16);
  if (Number.isNaN(n)) return [200, 200, 200];
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export function shade(c: RGB, f: number): RGB {
  return [c[0] * f, c[1] * f, c[2] * f].map((v) => Math.max(0, Math.min(255, Math.round(v)))) as RGB;
}
export function mix(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t].map((v) =>
    Math.round(v),
  ) as RGB;
}
export function css(c: RGB, a = 1): string {
  return a >= 1 ? `rgb(${c[0]},${c[1]},${c[2]})` : `rgba(${c[0]},${c[1]},${c[2]},${a})`;
}

/** A 16×16 (or any size) RGBA pixel buffer with helpers. */
class Px {
  data: Uint8ClampedArray;
  constructor(public w: number, public h: number, public r: () => number) {
    this.data = new Uint8ClampedArray(w * h * 4);
  }
  set(x: number, y: number, c: RGB, a = 255): void {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    const i = (y * this.w + x) * 4;
    this.data[i] = c[0];
    this.data[i + 1] = c[1];
    this.data[i + 2] = c[2];
    this.data[i + 3] = a;
  }
  get(x: number, y: number): RGB {
    const i = (((y + this.h) % this.h) * this.w + ((x + this.w) % this.w)) * 4;
    return [this.data[i], this.data[i + 1], this.data[i + 2]];
  }
  alpha(x: number, y: number): number {
    return this.data[(y * this.w + x) * 4 + 3];
  }
  fill(c: RGB, a = 255): void {
    for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) this.set(x, y, c, a);
  }
  rect(x0: number, y0: number, w: number, h: number, c: RGB | ((x: number, y: number) => RGB), a = 255): void {
    for (let y = y0; y < y0 + h; y++)
      for (let x = x0; x < x0 + w; x++) this.set(x, y, typeof c === 'function' ? c(x, y) : c, a);
  }
  /** fill with random picks from a palette (weights optional) */
  noise(pal: RGB[], x0 = 0, y0 = 0, w = this.w, h = this.h): void {
    for (let y = y0; y < y0 + h; y++)
      for (let x = x0; x < x0 + w; x++) this.set(x, y, pal[Math.floor(this.r() * pal.length)]);
  }
  /** multiply existing pixel brightness */
  mul(x: number, y: number, f: number): void {
    this.set(x, y, shade(this.get(x, y), f), this.alpha(x, y));
  }
  jitter(amount: number): void {
    for (let y = 0; y < this.h; y++)
      for (let x = 0; x < this.w; x++) {
        if (this.alpha(x, y) === 0) continue;
        this.mul(x, y, 1 + (this.r() - 0.5) * amount);
      }
  }
  toImageData(): ImageData {
    return new ImageData(this.data as unknown as Uint8ClampedArray<ArrayBuffer>, this.w, this.h);
  }
}

const P = (...cs: string[]): RGB[] => cs.map(hex);

// ---------------------------------------------------------------- tile painters
const DIRT = P('#7a5535', '#6b4a2e', '#86603c', '#5f4129', '#8f6a45');
const GRASS = P('#5c9e38', '#67aa3e', '#539331', '#72b546', '#4c8a2d');
const STONE = P('#7f7f80', '#898a8b', '#767677', '#929394', '#838485');

function voronoi(p: Px, n: number, pal: RGB[], mortar: RGB, edge = 1.15): void {
  const pts: { x: number; y: number; c: RGB }[] = [];
  for (let i = 0; i < n; i++) pts.push({ x: p.r() * 16, y: p.r() * 16, c: pal[Math.floor(p.r() * pal.length)] });
  for (let y = 0; y < 16; y++)
    for (let x = 0; x < 16; x++) {
      let d1 = 1e9;
      let d2 = 1e9;
      let best = pts[0];
      for (const q of pts)
        for (let ox = -16; ox <= 16; ox += 16)
          for (let oy = -16; oy <= 16; oy += 16) {
            const dx = x + 0.5 - (q.x + ox);
            const dy = y + 0.5 - (q.y + oy);
            const d = Math.sqrt(dx * dx + dy * dy);
            if (d < d1) {
              d2 = d1;
              d1 = d;
              best = q;
            } else if (d < d2) d2 = d;
          }
      if (d2 - d1 < edge) p.set(x, y, mortar);
      else {
        // highlight toward upper-left of each stone
        const f = 1.08 - Math.min(0.2, d1 / 18);
        p.set(x, y, shade(best.c, f + (p.r() - 0.5) * 0.08));
      }
    }
}

function planks(p: Px, base: RGB, seam: RGB): void {
  for (let b = 0; b < 4; b++) {
    const off = [3, 11, 6, 13][b];
    for (let y = b * 4; y < b * 4 + 4; y++)
      for (let x = 0; x < 16; x++) {
        let c = shade(base, 0.94 + p.r() * 0.1);
        if (y === b * 4) c = shade(base, 1.08);
        if (y === b * 4 + 3) c = seam;
        if ((x === off || x === (off + 8) % 16) && y !== b * 4 + 3 && b % 2 === 0 && x === off) c = seam;
        if (b % 2 === 1 && x === off) c = seam;
        p.set(x, y, c);
      }
    // wood grain streaks
    for (let k = 0; k < 3; k++) {
      const gy = b * 4 + 1 + Math.floor(p.r() * 2);
      const gx = Math.floor(p.r() * 16);
      for (let x = gx; x < gx + 3 + Math.floor(p.r() * 4); x++) p.set(x % 16, gy, shade(base, 0.86));
    }
  }
}

function bark(p: Px, pal: RGB[]): void {
  for (let x = 0; x < 16; x++) {
    const c = pal[Math.floor(p.r() * pal.length)];
    for (let y = 0; y < 16; y++) p.set(x, y, shade(c, 0.92 + p.r() * 0.14));
  }
  for (let k = 0; k < 10; k++) {
    const x = Math.floor(p.r() * 16);
    const y = Math.floor(p.r() * 14);
    const len = 2 + Math.floor(p.r() * 4);
    for (let i = 0; i < len; i++) p.set(x, y + i, shade(pal[0], 0.7));
  }
}

function logTop(p: Px, barkC: RGB, light: RGB, dark: RGB): void {
  for (let y = 0; y < 16; y++)
    for (let x = 0; x < 16; x++) {
      const d = Math.max(Math.abs(x - 7.5), Math.abs(y - 7.5));
      const ring = Math.floor(d);
      let c = ring % 2 === 0 ? light : dark;
      if (d > 6.6) c = shade(barkC, 0.9 + p.r() * 0.2);
      p.set(x, y, shade(c, 0.95 + p.r() * 0.1));
    }
}

function bricks(p: Px, base: RGB, mortar: RGB, rows = 4, hl = 1.12): void {
  const rh = 16 / rows;
  for (let y = 0; y < 16; y++)
    for (let x = 0; x < 16; x++) {
      const row = Math.floor(y / rh);
      const off = row % 2 ? rh * 1 : 0;
      const bx = (x + off) % 8;
      const by = y % rh;
      let c = shade(base, 0.93 + p.r() * 0.12);
      if (by === rh - 1 || bx === 7) c = mortar;
      else if (by === 0 || bx === 0) c = shade(base, hl);
      p.set(x, y, c);
    }
}

function wool(p: Px, base: RGB): void {
  for (let y = 0; y < 16; y++)
    for (let x = 0; x < 16; x++) {
      const w = ((x + y * 3) % 4 === 0 ? 0.92 : 1) * (0.94 + p.r() * 0.1);
      p.set(x, y, shade(base, w));
    }
}

function flower(p: Px, stem: RGB, petals: RGB[], center: RGB, tall = false): void {
  p.fill([0, 0, 0], 0);
  const sx = 7;
  const top = tall ? 3 : 6;
  for (let y = top + 2; y < 16; y++) p.set(sx + (y > 12 ? 0 : y % 5 === 0 ? 1 : 0), y, shade(stem, 0.9 + p.r() * 0.2));
  // leaves
  p.set(sx - 1, 12, stem);
  p.set(sx - 2, 11, stem);
  p.set(sx + 1, 13, stem);
  p.set(sx + 2, 12, shade(stem, 0.85));
  // petals
  const cy = top + 1;
  const pts = [
    [0, -1], [-1, 0], [1, 0], [0, 1], [-1, -1], [1, -1], [-1, 1], [1, 1], [0, -2], [-2, 0], [2, 0],
  ];
  for (const [dx, dy] of pts) p.set(sx + dx, cy + dy, petals[Math.floor(p.r() * petals.length)]);
  p.set(sx, cy, center);
}

function paint(t: number, p: Px): void {
  switch (t) {
    case T.GrassTop: {
      p.noise(GRASS);
      for (let k = 0; k < 18; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), shade(GRASS[0], 1.18));
      break;
    }
    case T.GrassSide:
    case T.PathSide: {
      p.noise(DIRT);
      const top = t === T.GrassSide ? GRASS : P('#9a7b4c', '#8f7045', '#a3844f');
      for (let x = 0; x < 16; x++) {
        const depth = t === T.GrassSide ? 3 + Math.floor(p.r() * 3) + (x % 3 === 0 ? 1 : 0) : 1 + Math.floor(p.r() * 2);
        for (let y = 0; y < depth; y++) p.set(x, y, top[Math.floor(p.r() * top.length)]);
        if (t === T.GrassSide) p.set(x, depth, shade(DIRT[1], 0.8));
      }
      break;
    }
    case T.Dirt:
      p.noise(DIRT);
      for (let k = 0; k < 6; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), hex('#a0866a'));
      break;
    case T.CoarseDirt:
      p.noise(DIRT);
      for (let k = 0; k < 20; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), hex('#4d3825'));
      for (let k = 0; k < 8; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), hex('#8c8c8c'));
      break;
    case T.Stone:
      p.noise(STONE);
      for (let k = 0; k < 7; k++) {
        const x = Math.floor(p.r() * 16);
        const y = Math.floor(p.r() * 16);
        for (let i = 0; i < 2 + Math.floor(p.r() * 3); i++) p.set((x + i) % 16, y, hex('#6a6a6b'));
      }
      break;
    case T.Cobble:
      voronoi(p, 9, P('#8d8d8d', '#7a7a7a', '#999999', '#6f6f6f'), hex('#4a4a4b'));
      break;
    case T.MossyCobble:
      voronoi(p, 9, P('#8d8d8d', '#7a7a7a', '#999999', '#6f6f6f'), hex('#4a4a4b'));
      for (let k = 0; k < 40; k++) {
        const x = Math.floor(p.r() * 16);
        const y = Math.floor(p.r() * 10);
        p.set(x, y, P('#557a33', '#62883a', '#4a6b2c')[Math.floor(p.r() * 3)]);
      }
      break;
    case T.Sand:
      p.noise(P('#dccf93', '#e4d9a1', '#d4c686', '#e9dfae', '#cfc07e'));
      break;
    case T.Gravel:
      voronoi(p, 22, P('#8a8481', '#6f6966', '#9d9793', '#7b6f66', '#5e5a58'), hex('#56504d'), 0.6);
      break;
    case T.OakLog:
      bark(p, P('#6b5232', '#5b4427', '#77603c', '#4f3b22'));
      break;
    case T.OakLogTop:
      logTop(p, hex('#5b4427'), hex('#b8955c'), hex('#a07f4b'));
      break;
    case T.DarkLog:
      bark(p, P('#3f2c1a', '#342414', '#4a3520', '#2b1d10'));
      break;
    case T.DarkLogTop:
      logTop(p, hex('#342414'), hex('#6b4c2d'), hex('#583d23'));
      break;
    case T.OakLeaves:
    case T.BlossomLeaves: {
      const pal =
        t === T.OakLeaves
          ? P('#3d7a28', '#488a2f', '#336b22', '#56993a', '#2e6120')
          : P('#f4b3cb', '#eb98b8', '#f8c8da', '#de80a5', '#f0a6c1');
      for (let y = 0; y < 16; y++)
        for (let x = 0; x < 16; x++) {
          const hole = p.r() < 0.1;
          if (hole) p.set(x, y, [0, 0, 0], 0);
          else p.set(x, y, pal[Math.floor(p.r() * pal.length)]);
        }
      if (t === T.BlossomLeaves) for (let k = 0; k < 10; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), hex('#6f9e45'));
      else for (let k = 0; k < 12; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), hex('#6aad44'));
      break;
    }
    case T.OakPlanks:
      planks(p, hex('#b08853'), hex('#7a5a33'));
      break;
    case T.DarkPlanks:
      planks(p, hex('#5c3f24'), hex('#3a2715'));
      break;
    case T.StoneBricks:
      bricks(p, hex('#8e8e90'), hex('#5e5e60'), 2);
      break;
    case T.MossyBricks:
      bricks(p, hex('#8e8e90'), hex('#5e5e60'), 2);
      for (let k = 0; k < 34; k++) {
        const x = Math.floor(p.r() * 16);
        const y = Math.floor(p.r() * 16);
        if (p.r() < 0.6 || y > 10) p.set(x, y, P('#5a7d34', '#678c3c', '#4b6a2b')[Math.floor(p.r() * 3)]);
      }
      break;
    case T.Bricks:
      bricks(p, hex('#9b4b3a'), hex('#c9b8a6'), 4, 1.1);
      break;
    case T.Gold:
    case T.GoldTrim: {
      const g = hex('#f2c83a');
      p.rect(0, 0, 16, 16, () => shade(g, 0.95 + p.r() * 0.08));
      for (let i = 0; i < 16; i++) {
        p.set(i, 0, hex('#fff2a0'));
        p.set(0, i, hex('#fbe479'));
        p.set(i, 15, hex('#b8861d'));
        p.set(15, i, hex('#c9951f'));
      }
      if (t === T.GoldTrim) {
        // bevelled inner panel
        for (let i = 2; i < 14; i++) {
          p.set(i, 2, hex('#c9951f'));
          p.set(2, i, hex('#c9951f'));
          p.set(i, 13, hex('#fff2a0'));
          p.set(13, i, hex('#fbe479'));
        }
        p.set(4, 4, hex('#ffffff'));
      } else {
        p.set(3, 3, hex('#ffffff'));
        p.set(4, 3, hex('#fff6c0'));
        p.set(3, 4, hex('#fff6c0'));
        p.set(11, 9, hex('#fff6c0'));
      }
      break;
    }
    case T.PurpleWool:
      wool(p, hex('#7d3fb0'));
      break;
    case T.RedWool:
      wool(p, hex('#b0302c'));
      break;
    case T.WhiteWool:
      wool(p, hex('#e9ecec'));
      break;
    case T.YellowWool:
      wool(p, hex('#f5c13a'));
      break;
    case T.SmoothStone: {
      p.rect(0, 0, 16, 16, () => shade(hex('#a3a4a6'), 0.96 + p.r() * 0.07));
      for (let i = 0; i < 16; i++) {
        p.set(i, 0, hex('#b9babc'));
        p.set(i, 15, hex('#77787a'));
        p.set(0, i, hex('#b2b3b5'));
        p.set(15, i, hex('#808183'));
      }
      break;
    }
    case T.Quartz: {
      p.rect(0, 0, 16, 16, () => shade(hex('#ece6dc'), 0.96 + p.r() * 0.05));
      for (let i = 1; i < 15; i++) {
        p.set(i, 1, hex('#d8d0c2'));
        p.set(i, 14, hex('#d8d0c2'));
        p.set(1, i, hex('#d8d0c2'));
        p.set(14, i, hex('#d8d0c2'));
      }
      break;
    }
    case T.PathTop:
      p.noise(P('#a1824f', '#957646', '#ab8c58', '#8a6c40'));
      for (let k = 0; k < 10; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), hex('#7b5d37'));
      break;
    case T.CraftTop: {
      planks(p, hex('#b08853'), hex('#7a5a33'));
      const fr = hex('#5a3f22');
      for (let i = 0; i < 16; i++) {
        p.set(i, 0, fr);
        p.set(i, 15, fr);
        p.set(0, i, fr);
        p.set(15, i, fr);
      }
      for (let i = 2; i < 14; i++) {
        p.set(i, 5, fr);
        p.set(i, 10, fr);
        p.set(5, i, fr);
        p.set(10, i, fr);
      }
      break;
    }
    case T.CraftSide:
    case T.CraftFront: {
      planks(p, hex('#a67d49'), hex('#6f5130'));
      p.rect(0, 0, 16, 3, () => shade(hex('#8a6438'), 0.95 + p.r() * 0.1));
      const metal = hex('#b5b5b8');
      const handle = hex('#5a3f22');
      if (t === T.CraftFront) {
        // saw
        for (let x = 3; x < 11; x++) p.set(x, 7, metal);
        for (let x = 3; x < 11; x += 2) p.set(x, 8, hex('#8a8a8e'));
        p.rect(11, 6, 2, 3, handle);
        // hammer
        p.rect(4, 11, 4, 2, hex('#7f7f83'));
        for (let y = 11; y < 15; y++) p.set(9, y, handle);
      } else {
        // pliers + chisel
        for (let y = 5; y < 12; y++) p.set(4, y, handle);
        p.rect(3, 4, 3, 2, metal);
        for (let y = 5; y < 13; y++) p.set(10 + (y % 2), y, metal);
        p.rect(10, 12, 2, 2, handle);
      }
      break;
    }
    case T.FurnaceSide:
    case T.FurnaceTop:
      voronoi(p, 10, P('#8a8a8b', '#7d7d7e', '#949495'), hex('#5a5a5b'), 0.8);
      if (t === T.FurnaceTop) p.rect(3, 3, 10, 10, (x, y) => shade(hex('#6d6d6e'), 0.95 + ((x + y) % 2) * 0.05));
      break;
    case T.FurnaceFront: {
      voronoi(p, 10, P('#8a8a8b', '#7d7d7e', '#949495'), hex('#5a5a5b'), 0.8);
      p.rect(3, 8, 10, 6, hex('#2a2a2a'));
      for (let x = 4; x < 12; x++) {
        p.set(x, 12, P('#ff9a2e', '#ffcf4a', '#e8611c')[Math.floor(p.r() * 3)]);
        if (p.r() < 0.6) p.set(x, 11, P('#ff9a2e', '#e8611c')[Math.floor(p.r() * 2)]);
        if (p.r() < 0.25) p.set(x, 10, hex('#ffcf4a'));
      }
      p.rect(3, 3, 10, 2, hex('#5a5a5b'));
      break;
    }
    case T.Bookshelf: {
      planks(p, hex('#b08853'), hex('#7a5a33'));
      const books = P('#8c2f2f', '#2f5a8c', '#3f7a3a', '#8c6a2f', '#5a2f8c', '#c9c0a8', '#2f7a7a');
      for (const row of [1, 9]) {
        p.rect(0, row, 16, 6, hex('#3a2715'));
        let x = 1;
        while (x < 15) {
          const w = 1 + (p.r() < 0.3 ? 1 : 0);
          const c = books[Math.floor(p.r() * books.length)];
          const h = 4 + Math.floor(p.r() * 2);
          for (let i = 0; i < w && x < 15; i++, x++)
            for (let y = row + 6 - h; y < row + 6; y++) p.set(x, y, shade(c, y === row + 6 - h ? 1.15 : 0.95));
          if (p.r() < 0.2) x++;
        }
      }
      break;
    }
    case T.EnchantTop: {
      p.rect(0, 0, 16, 16, () => shade(hex('#a3262b'), 0.92 + p.r() * 0.12));
      for (let i = 0; i < 16; i++) {
        p.set(i, 0, hex('#1e1530'));
        p.set(i, 15, hex('#1e1530'));
        p.set(0, i, hex('#1e1530'));
        p.set(15, i, hex('#1e1530'));
      }
      const dia = hex('#5ef0e0');
      for (const [x, y] of [[2, 2], [13, 2], [2, 13], [13, 13]]) {
        p.set(x, y, dia);
        p.set(x + 1, y, shade(dia, 0.8));
        p.set(x, y + 1, shade(dia, 0.8));
      }
      for (let i = 4; i < 12; i++) p.set(i, i, hex('#c9404a'));
      for (let i = 4; i < 12; i++) p.set(15 - i, i, hex('#c9404a'));
      break;
    }
    case T.EnchantSide: {
      p.noise(P('#1e1530', '#150f22', '#2a1f40'));
      p.rect(0, 0, 16, 4, () => shade(hex('#a3262b'), 0.92 + p.r() * 0.12));
      p.set(3, 9, hex('#6b4fb0'));
      p.set(12, 11, hex('#6b4fb0'));
      break;
    }
    case T.Obsidian:
      p.noise(P('#1e1530', '#150f22', '#2a1f40', '#18112a'));
      for (let k = 0; k < 6; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), hex('#5a3f8c'));
      break;
    case T.Glass: {
      p.fill([0, 0, 0], 0);
      const f = hex('#dff4f8');
      for (let i = 0; i < 16; i++) {
        p.set(i, 0, f);
        p.set(i, 15, shade(f, 0.85));
        p.set(0, i, f);
        p.set(15, i, shade(f, 0.85));
      }
      for (let i = 0; i < 4; i++) p.set(3 + i, 5 - i, f);
      for (let i = 0; i < 3; i++) p.set(9 + i, 12 - i, f);
      break;
    }
    case T.Lantern: {
      p.fill(hex('#3b3430'));
      p.rect(2, 2, 12, 12, (x, y) => {
        const d = Math.max(Math.abs(x - 7.5), Math.abs(y - 7.5));
        return d < 3 ? hex('#fff1b8') : d < 5 ? hex('#ffd36a') : hex('#f2a23a');
      });
      for (let i = 0; i < 16; i += 5) {
        for (let y = 2; y < 14; y++) p.set(i === 15 ? 14 : i, y, hex('#3b3430'));
      }
      p.rect(0, 0, 16, 2, hex('#2d2724'));
      p.rect(0, 14, 16, 2, hex('#2d2724'));
      break;
    }
    case T.FlowerRed:
      flower(p, hex('#3f7a2a'), P('#d8322a', '#b8261f', '#e84a3a'), hex('#1e1a14'));
      break;
    case T.FlowerYellow:
      flower(p, hex('#4a8a2f'), P('#f7d23a', '#f0c020', '#ffe46a'), hex('#e0a020'));
      break;
    case T.FlowerBlue:
      flower(p, hex('#3f7a2a'), P('#4a6fe0', '#3a58c8', '#6b8bf0'), hex('#2a3a80'), true);
      break;
    case T.FlowerPink:
      flower(p, hex('#3f7a2a'), P('#f08cb8', '#e070a0', '#f8b0d0'), hex('#fff0f6'), true);
      break;
    case T.TallGrass:
    case T.Fern: {
      p.fill([0, 0, 0], 0);
      const pal = t === T.TallGrass ? P('#5a9c36', '#6aaf42', '#4d8a2c', '#78bd4c') : P('#3f7f2c', '#4c9034', '#356e25');
      const blades = t === T.TallGrass ? 7 : 5;
      for (let b = 0; b < blades; b++) {
        let x = 1 + Math.floor(p.r() * 14);
        const h = 6 + Math.floor(p.r() * 9);
        const lean = p.r() < 0.5 ? -1 : 1;
        for (let i = 0; i < h; i++) {
          const y = 15 - i;
          p.set(x, y, pal[Math.floor(p.r() * pal.length)]);
          if (t === T.TallGrass && i < h - 2) p.set(x + 1, y, shade(pal[Math.floor(p.r() * pal.length)], 0.9));
          if (t === T.Fern && i % 2 === 1) {
            p.set(x - 1, y, pal[1]);
            p.set(x + 1, y, pal[2]);
          }
          if (i > h / 2 && p.r() < 0.35) x += lean;
        }
      }
      break;
    }
    case T.Wheat: {
      p.fill([0, 0, 0], 0);
      const stalk = P('#b8a040', '#c9b24a', '#a08a30');
      const head = P('#e8c860', '#d9b44a', '#f0d878');
      for (let k = 0; k < 6; k++) {
        const x = 1 + k * 2 + Math.floor(p.r() * 2);
        const h = 9 + Math.floor(p.r() * 5);
        for (let i = 0; i < h; i++) p.set(x, 15 - i, i > h - 5 ? head[Math.floor(p.r() * 3)] : stalk[Math.floor(p.r() * 3)]);
        p.set(x + 1, 15 - h + 2, head[1]);
        p.set(x - 1, 15 - h + 3, head[2]);
      }
      break;
    }
    case T.FarmTop: {
      for (let y = 0; y < 16; y++)
        for (let x = 0; x < 16; x++) {
          const furrow = y % 4 === 0 || y % 4 === 3;
          p.set(x, y, shade(hex(furrow ? '#4a3220' : '#6a4a2e'), 0.92 + p.r() * 0.14));
        }
      break;
    }
    case T.Mushroom: {
      p.fill([0, 0, 0], 0);
      p.rect(7, 10, 2, 6, hex('#e8dccb'));
      p.rect(4, 7, 8, 3, hex('#c8322a'));
      p.rect(5, 6, 6, 1, hex('#d8423a'));
      p.set(6, 8, hex('#ffffff'));
      p.set(9, 7, hex('#ffffff'));
      break;
    }
    case T.Water: {
      const pal = P('#2f6fcf', '#3a7cdc', '#2a63be', '#3f86e3');
      p.noise(pal);
      for (let k = 0; k < 5; k++) {
        const y = Math.floor(p.r() * 16);
        const x = Math.floor(p.r() * 16);
        for (let i = 0; i < 4; i++) p.set((x + i) % 16, y, hex('#6fa8f0'));
      }
      break;
    }
    case T.HayTop:
    case T.HaySide: {
      const pal = P('#d9b43a', '#c9a230', '#e6c54a', '#b89028');
      if (t === T.HaySide) {
        for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) p.set(x, y, pal[(x * 7 + Math.floor(p.r() * 2)) % pal.length]);
        p.rect(0, 3, 16, 2, hex('#8f3a24'));
        p.rect(0, 11, 16, 2, hex('#8f3a24'));
      } else {
        p.noise(pal);
        for (let i = 0; i < 16; i++) {
          p.set(i, 0, hex('#8f3a24'));
          p.set(i, 15, hex('#8f3a24'));
        }
      }
      break;
    }
    case T.BarrelTop:
    case T.BarrelSide: {
      if (t === T.BarrelSide) {
        planks(p, hex('#8a6038'), hex('#5c3d20'));
        for (let x = 0; x < 16; x += 4) for (let y = 0; y < 16; y++) p.set(x, y, hex('#5c3d20'));
        p.rect(0, 2, 16, 1, hex('#4a4a4e'));
        p.rect(0, 13, 16, 1, hex('#4a4a4e'));
      } else {
        planks(p, hex('#9a6c40'), hex('#5c3d20'));
        for (let i = 0; i < 16; i++) {
          p.set(i, 0, hex('#4a4a4e'));
          p.set(i, 15, hex('#4a4a4e'));
          p.set(0, i, hex('#4a4a4e'));
          p.set(15, i, hex('#4a4a4e'));
        }
        p.rect(6, 6, 4, 4, hex('#3a2715'));
      }
      break;
    }
    case T.Amethyst: {
      p.noise(P('#8d5fd3', '#a57be6', '#7a4bc0', '#b894f0'));
      for (let k = 0; k < 6; k++) p.set(Math.floor(p.r() * 16), Math.floor(p.r() * 16), hex('#f0e0ff'));
      break;
    }
    case T.ChestFront:
    case T.ChestSide:
    case T.ChestTop: {
      planks(p, hex('#a8702e'), hex('#6e4518'));
      const band = hex('#3a2a14');
      for (let i = 0; i < 16; i++) {
        p.set(i, 0, band);
        p.set(i, 15, band);
        p.set(0, i, band);
        p.set(15, i, band);
      }
      if (t !== T.ChestTop) p.rect(0, 5, 16, 1, band);
      if (t === T.ChestFront) {
        p.rect(7, 4, 2, 4, hex('#cfcfd4'));
        p.set(7, 7, hex('#8a8a90'));
      }
      break;
    }
    case T.AnvilTop:
    case T.IronBlock: {
      const base = t === T.AnvilTop ? hex('#4a4a4f') : hex('#c8c9cc');
      p.rect(0, 0, 16, 16, () => shade(base, 0.94 + p.r() * 0.1));
      for (let i = 0; i < 16; i++) {
        p.set(i, 0, shade(base, 1.2));
        p.set(i, 15, shade(base, 0.75));
      }
      if (t === T.AnvilTop) p.rect(3, 4, 10, 8, () => shade(hex('#5d5d63'), 0.95 + p.r() * 0.1));
      else for (let y = 3; y < 16; y += 5) p.rect(0, y, 16, 1, shade(base, 0.85));
      break;
    }
    case T.LecternTop: {
      planks(p, hex('#b08853'), hex('#7a5a33'));
      // open book
      p.rect(2, 3, 12, 10, hex('#7a3b1f'));
      p.rect(3, 4, 5, 8, hex('#efe6cf'));
      p.rect(8, 4, 5, 8, hex('#e6dcc0'));
      for (let y = 5; y < 11; y += 2) {
        p.rect(4, y, 3, 1, hex('#8a8272'));
        p.rect(9, y, 3, 1, hex('#8a8272'));
      }
      break;
    }
    case T.LecternSide: {
      planks(p, hex('#a67d49'), hex('#6f5130'));
      p.rect(4, 0, 8, 16, () => shade(hex('#8a6438'), 0.95 + p.r() * 0.1));
      p.rect(4, 0, 1, 16, hex('#5a3f22'));
      p.rect(11, 0, 1, 16, hex('#5a3f22'));
      break;
    }
    case T.Sapling:
    default:
      p.noise(P('#ff00ff', '#000000'));
  }
}

export const ATLAS_COLS = 8;
export const ATLAS_CELL = 32;
export const ATLAS_SIZE = ATLAS_COLS * ATLAS_CELL; // 256

let atlasTex: THREE.DataTexture | null = null;
const tileCanvases = new Map<number, HTMLCanvasElement>();
const tilePx = new Map<number, Px>();

function tilePixels(t: number): Px {
  let p = tilePx.get(t);
  if (p) return p;
  p = new Px(16, 16, rng(1000 + t * 7919));
  paint(t, p);
  // colour-bleed: transparent texels take the average opaque colour so mipmaps don't darken edges
  let r = 0;
  let g = 0;
  let b = 0;
  let n = 0;
  for (let i = 0; i < p.data.length; i += 4)
    if (p.data[i + 3] > 0) {
      r += p.data[i];
      g += p.data[i + 1];
      b += p.data[i + 2];
      n++;
    }
  if (n > 0 && n < 256)
    for (let i = 0; i < p.data.length; i += 4)
      if (p.data[i + 3] === 0) {
        p.data[i] = r / n;
        p.data[i + 1] = g / n;
        p.data[i + 2] = b / n;
      }
  tilePx.set(t, p);
  return p;
}

export function tileCanvas(t: number): HTMLCanvasElement {
  let c = tileCanvases.get(t);
  if (c) return c;
  c = document.createElement('canvas');
  c.width = c.height = 16;
  c.getContext('2d')!.putImageData(tilePixels(t).toImageData(), 0, 0);
  tileCanvases.set(t, c);
  return c;
}

/**
 * Padded atlas built from raw pixels (not a canvas, which would premultiply alpha): each 16px tile
 * sits in a 32px cell, wrapped into its 8px gutter so mipmaps don't bleed between tiles.
 */
export function getAtlas(): THREE.DataTexture {
  if (atlasTex) return atlasTex;
  const S = ATLAS_SIZE;
  const data = new Uint8Array(S * S * 4);
  for (let t = 0; t < T.Count; t++) {
    const p = tilePixels(t);
    const cx = (t % ATLAS_COLS) * ATLAS_CELL;
    const cy = Math.floor(t / ATLAS_COLS) * ATLAS_CELL;
    for (let y = 0; y < ATLAS_CELL; y++)
      for (let x = 0; x < ATLAS_CELL; x++) {
        const sx = (((x - 8) % 16) + 16) % 16;
        const sy = (((y - 8) % 16) + 16) % 16;
        const si = (sy * 16 + sx) * 4;
        const di = ((cy + y) * S + (cx + x)) * 4;
        data[di] = p.data[si];
        data[di + 1] = p.data[si + 1];
        data[di + 2] = p.data[si + 2];
        data[di + 3] = p.data[si + 3];
      }
  }
  const tex = new THREE.DataTexture(data, S, S, THREE.RGBAFormat, THREE.UnsignedByteType);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.NearestMipmapLinearFilter;
  tex.generateMipmaps = true;
  tex.flipY = false;
  tex.anisotropy = 4;
  tex.needsUpdate = true;
  atlasTex = tex;
  return tex;
}

/** UV rect (top-left origin, flipY=false) of a tile's 16px interior. */
export function tileUV(t: number): [number, number, number, number] {
  const cx = (t % ATLAS_COLS) * ATLAS_CELL + 8;
  const cy = Math.floor(t / ATLAS_COLS) * ATLAS_CELL + 8;
  return [cx / ATLAS_SIZE, cy / ATLAS_SIZE, (cx + 16) / ATLAS_SIZE, (cy + 16) / ATLAS_SIZE];
}

const sharedTiles = new Map<number, THREE.CanvasTexture>();
/** Cached single-tile texture shared by many materials (hats, tools). Never dispose it per-user. */
export function sharedTileTexture(t: number): THREE.CanvasTexture {
  let tex = sharedTiles.get(t);
  if (!tex) {
    tex = tileTexture(t);
    sharedTiles.set(t, tex);
  }
  return tex;
}

/** A standalone repeat-wrapping texture of a single tile (used for water, ocean floor). */
export function tileTexture(t: number, repeat = 1): THREE.CanvasTexture {
  const tex = new THREE.CanvasTexture(tileCanvas(t));
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.NearestMipmapLinearFilter;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(repeat, repeat);
  return tex;
}

export function pixelTexture(canvas: HTMLCanvasElement): THREE.CanvasTexture {
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  return tex;
}

// ---------------------------------------------------------------- villager skins
// 64×64 layout (top-left origin). Box face rects follow the classic cross layout:
// for a box w×h×d at (u,v): top(u+d,v,w,d) bottom(u+d+w,v,w,d)
// right(u,v+d,d,h) front(u+d,v+d,w,h) left(u+d+w,v+d,d,h) back(u+2d+w,v+d,w,h)
export const SKIN_UV = {
  head: { u: 0, v: 0, w: 8, h: 8, d: 8 },
  body: { u: 16, v: 16, w: 8, h: 12, d: 4 },
  arm: { u: 40, v: 16, w: 4, h: 12, d: 4 },
  leg: { u: 0, v: 16, w: 4, h: 12, d: 4 },
  cape: { u: 0, v: 32, w: 10, h: 16, d: 1 },
} as const;

export type BoxUV = (typeof SKIN_UV)[keyof typeof SKIN_UV];

export function faceRects(b: BoxUV): Record<'top' | 'bottom' | 'right' | 'front' | 'left' | 'back', [number, number, number, number]> {
  const { u, v, w, h, d } = b;
  return {
    top: [u + d, v, w, d],
    bottom: [u + d + w, v, w, d],
    right: [u, v + d, d, h],
    front: [u + d, v + d, w, h],
    left: [u + d + w, v + d, d, h],
    back: [u + 2 * d + w, v + d, w, h],
  };
}

const LONG_SLEEVE_HATS = new Set(['crown', 'wizard', 'hood']);

export function skinCanvas(spec: SkinSpec, seedKey: string): HTMLCanvasElement {
  const p = new Px(64, 64, rng(hashString(seedKey) ^ 0x51f15e));
  p.fill([0, 0, 0], 0);
  const skin = hex(spec.skin);
  const hair = hex(spec.hair);
  const eyes = hex(spec.eyes);
  const shirt = hex(spec.shirt);
  const pants = hex(spec.pants);
  const shoes = hex(spec.shoes);
  const accent = hex(spec.accent);
  const n = (c: RGB, amt = 0.06): RGB => shade(c, 1 + (p.r() - 0.5) * amt * 2);
  const robe = LONG_SLEEVE_HATS.has(spec.hat);

  // ---- head
  const H = faceRects(SKIN_UV.head);
  const fillRect = (r: [number, number, number, number], fn: (x: number, y: number) => RGB): void => {
    for (let y = 0; y < r[3]; y++) for (let x = 0; x < r[2]; x++) p.set(r[0] + x, r[1] + y, fn(x, y));
  };
  fillRect(H.top, () => n(hair, 0.08));
  fillRect(H.bottom, () => n(shade(skin, 0.85)));
  const hairStyle = hashString(seedKey) % 3; // 0 short, 1 fringe, 2 long
  fillRect(H.front, (x, y) => {
    if (y === 0) return n(hair, 0.08);
    if (y === 1 && (hairStyle !== 0 || x < 2 || x > 5)) return n(hair, 0.08);
    if (y === 2 && hairStyle === 1 && (x < 3 || x > 6)) return n(shade(hair, 0.9));
    if ((x === 0 || x === 7) && y < (hairStyle === 2 ? 6 : 3)) return n(shade(hair, 0.92));
    let c = n(skin, 0.035);
    if (y === 1 || y === 2) c = shade(c, 1.04);
    if (y >= 6) c = shade(c, 0.96);
    return c;
  });
  const fx = H.front[0];
  const fy = H.front[1];
  // eyebrows
  const brow = shade(hair, 0.75);
  p.set(fx + 1, fy + 3, brow);
  p.set(fx + 2, fy + 3, brow);
  p.set(fx + 5, fy + 3, brow);
  p.set(fx + 6, fy + 3, brow);
  // eyes: white + pupil, pupils toward the centre
  p.set(fx + 1, fy + 4, [242, 242, 238]);
  p.set(fx + 2, fy + 4, eyes);
  p.set(fx + 5, fy + 4, eyes);
  p.set(fx + 6, fy + 4, [242, 242, 238]);
  // nose + mouth shading
  p.set(fx + 3, fy + 5, shade(skin, 0.86));
  p.set(fx + 4, fy + 5, shade(skin, 0.86));
  p.set(fx + 3, fy + 6, shade(skin, 0.7));
  p.set(fx + 4, fy + 6, shade(skin, 0.7));
  p.set(fx + 2, fy + 6, shade(skin, 0.82));
  p.set(fx + 5, fy + 6, shade(skin, 0.82));
  // cheeks blush
  p.set(fx + 1, fy + 5, mix(skin, [220, 120, 120], 0.18));
  p.set(fx + 6, fy + 5, mix(skin, [220, 120, 120], 0.18));
  if (hairStyle !== 2) {
    // a little beard-shadow for some seeds
    if (hashString(seedKey + 'b') % 4 === 0)
      for (let x = 1; x < 7; x++) p.set(fx + x, fy + 7, shade(hair, 0.95));
  }
  // sides: right (-x) face has front on the RIGHT edge of its rect in BoxGeometry; left (+x) face has front on the LEFT.
  const hairDepth = hairStyle === 2 ? 7 : 4;
  fillRect(H.right, (x, y) => {
    const fromBack = x; // column 0 = back
    if (y < 2 || (fromBack < 8 - 3 && y < hairDepth) || (fromBack < 3 && y < 8)) return n(hair, 0.08);
    return n(skin, 0.035);
  });
  fillRect(H.left, (x, y) => {
    const fromBack = 7 - x; // column 7 = back
    if (y < 2 || (fromBack < 8 - 3 && y < hairDepth) || (fromBack < 3 && y < 8)) return n(hair, 0.08);
    return n(skin, 0.035);
  });
  // ears
  p.set(H.right[0] + 4, H.right[1] + 4, shade(skin, 0.88));
  p.set(H.left[0] + 3, H.left[1] + 4, shade(skin, 0.88));
  fillRect(H.back, (_x, y) => (y < (hairStyle === 2 ? 8 : 7) ? n(hair, 0.08) : n(shade(skin, 0.95))));

  // ---- body
  const Bd = faceRects(SKIN_UV.body);
  const shirtAt = (x: number, y: number, w: number): RGB => {
    let c = n(shirt, 0.05);
    if (x === 0 || x === w - 1) c = shade(c, 0.9);
    if (y > 7) c = shade(c, 0.94);
    if (y === 0) c = shade(c, 1.06);
    return c;
  };
  const beltRow = 8;
  const bodyFace = (r: [number, number, number, number]): void =>
    fillRect(r, (x, y) => {
      if (y === beltRow) return n(accent, 0.04);
      if (!robe && y > beltRow) return n(pants, 0.05);
      if (robe && y > beltRow) return shade(shirtAt(x, y, r[2]), 0.9);
      return shirtAt(x, y, r[2]);
    });
  bodyFace(Bd.front);
  bodyFace(Bd.back);
  bodyFace(Bd.left);
  bodyFace(Bd.right);
  fillRect(Bd.top, () => n(shirt));
  fillRect(Bd.bottom, () => n(robe ? shade(shirt, 0.85) : pants));
  {
    const [bx, by] = Bd.front;
    // collar
    p.set(bx + 3, by, n(skin));
    p.set(bx + 4, by, n(skin));
    p.set(bx + 3, by + 1, shade(skin, 0.9));
    p.set(bx + 4, by + 1, shade(skin, 0.9));
    p.set(bx + 2, by, shade(shirt, 0.8));
    p.set(bx + 5, by, shade(shirt, 0.8));
    // buckle
    p.set(bx + 3, by + beltRow, [230, 200, 90]);
    p.set(bx + 4, by + beltRow, [200, 170, 70]);
    if (robe) {
      // robe centre trim
      for (let y = 2; y < 12; y++) if (y !== beltRow) p.set(bx + 4, by + y, n(shade(accent, 0.95)));
      for (let x = 0; x < 8; x++) p.set(bx + x, by + 11, n(accent));
    } else {
      // buttons / pocket
      p.set(bx + 4, by + 3, shade(shirt, 0.75));
      p.set(bx + 4, by + 5, shade(shirt, 0.75));
      p.set(bx + 1, by + 3, shade(shirt, 0.85));
      p.set(bx + 2, by + 3, shade(shirt, 0.85));
    }
  }

  // ---- arm
  const A = faceRects(SKIN_UV.arm);
  const sleeve = robe ? 9 : 4;
  const armFace = (r: [number, number, number, number]): void =>
    fillRect(r, (x, y) => {
      if (y < sleeve) return shade(shirtAt(x, y, r[2]), y === 0 ? 1 : 0.98);
      if (y === sleeve) return n(accent);
      let c = n(skin, 0.035);
      if (y >= 10) c = shade(c, 0.95);
      return c;
    });
  armFace(A.front);
  armFace(A.back);
  armFace(A.left);
  armFace(A.right);
  fillRect(A.top, () => n(shirt));
  fillRect(A.bottom, () => n(shade(skin, 0.9)));

  // ---- leg
  const L = faceRects(SKIN_UV.leg);
  const legFace = (r: [number, number, number, number]): void =>
    fillRect(r, (x, y) => {
      if (robe && y < 5) return n(shade(shirt, 0.88));
      if (y >= 10) return n(shoes, 0.05);
      let c = n(pants, 0.05);
      if (x === 0) c = shade(c, 0.9);
      if (y === 9) c = shade(c, 0.85);
      return c;
    });
  legFace(L.front);
  legFace(L.back);
  legFace(L.left);
  legFace(L.right);
  fillRect(L.top, () => n(pants));
  fillRect(L.bottom, () => n(shade(shoes, 0.8)));

  // ---- cape
  const capeC = hex(spec.cape ?? spec.accent);
  const Cp = faceRects(SKIN_UV.cape);
  const capeFace = (r: [number, number, number, number], trim: boolean): void =>
    fillRect(r, (x, y) => {
      if (trim && (x === 0 || x === r[2] - 1 || y === r[3] - 1)) return n(accent);
      let c = n(capeC, 0.05);
      if (y > 10) c = shade(c, 0.93);
      return c;
    });
  capeFace(Cp.front, true);
  capeFace(Cp.back, true);
  capeFace(Cp.left, false);
  capeFace(Cp.right, false);
  capeFace(Cp.top, false);
  capeFace(Cp.bottom, false);
  {
    // emblem on the outside (back) of the cape
    const [cx, cy] = Cp.back;
    const g: RGB = hex(spec.accent);
    for (const [dx, dy] of [[4, 4], [5, 4], [4, 5], [5, 5], [4, 3], [5, 6], [3, 4], [6, 5]]) p.set(cx + dx, cy + dy, g);
  }

  const c = document.createElement('canvas');
  c.width = c.height = 64;
  c.getContext('2d')!.putImageData(p.toImageData(), 0, 0);
  return c;
}

// ---------------------------------------------------------------- misc sprites
function makeCanvas(w: number, h: number, draw: (ctx: CanvasRenderingContext2D) => void): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d')!;
  ctx.imageSmoothingEnabled = false;
  draw(ctx);
  return c;
}

export function sunCanvas(): HTMLCanvasElement {
  return makeCanvas(16, 16, (ctx) => {
    ctx.fillStyle = '#ffd86a';
    ctx.fillRect(0, 0, 16, 16);
    ctx.fillStyle = '#fff3b8';
    ctx.fillRect(2, 2, 12, 12);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(4, 4, 8, 8);
    ctx.fillStyle = '#fffbe6';
    ctx.fillRect(5, 5, 2, 2);
  });
}

export function moonCanvas(): HTMLCanvasElement {
  return makeCanvas(16, 16, (ctx) => {
    ctx.fillStyle = '#c9d2e6';
    ctx.fillRect(1, 1, 14, 14);
    ctx.fillStyle = '#e8eefc';
    ctx.fillRect(3, 2, 10, 12);
    ctx.fillStyle = '#aab4cc';
    for (const [x, y, w] of [[4, 4, 2], [9, 6, 3], [6, 10, 2], [11, 11, 1]]) ctx.fillRect(x, y, w, w);
  });
}

export function bannerCanvas(base: string, emblem: string): HTMLCanvasElement {
  const r = rng(hashString(base + emblem));
  return makeCanvas(16, 32, (ctx) => {
    const b = hex(base);
    for (let y = 0; y < 32; y++)
      for (let x = 0; x < 16; x++) {
        ctx.fillStyle = css(shade(b, 0.92 + r() * 0.12 - (y > 26 ? 0.1 : 0)));
        ctx.fillRect(x, y, 1, 1);
      }
    const e = hex(emblem);
    ctx.fillStyle = css(e);
    ctx.fillRect(0, 0, 16, 2);
    ctx.fillRect(0, 2, 1, 26);
    ctx.fillRect(15, 2, 1, 26);
    // stylised eye-in-diamond emblem
    for (let i = 0; i < 5; i++) {
      ctx.fillRect(7 - i, 8 + i, 2 + i * 2, 1);
      ctx.fillRect(7 - i, 18 - i, 2 + i * 2, 1);
    }
    ctx.fillStyle = css(b);
    ctx.fillRect(5, 11, 6, 4);
    ctx.fillStyle = css(e);
    ctx.fillRect(7, 12, 2, 2);
    // zig-zag bottom
    ctx.fillStyle = css(shade(e, 0.9));
    for (let x = 0; x < 16; x++) ctx.fillRect(x, 26 + (x % 4 < 2 ? 0 : 1), 1, 1);
    ctx.clearRect(0, 30, 16, 2);
    for (let x = 0; x < 16; x++) if (x % 4 === 0 || x % 4 === 3) ctx.clearRect(x, 28, 1, 2);
    ctx.fillStyle = css(shade(b, 0.8));
    for (let x = 1; x < 15; x++) if (x % 4 === 1 || x % 4 === 2) ctx.fillRect(x, 28, 1, 2);
  });
}

export function scrollCanvas(): HTMLCanvasElement {
  return makeCanvas(16, 16, (ctx) => {
    ctx.fillStyle = '#f1e2b8';
    ctx.fillRect(1, 3, 14, 10);
    ctx.fillStyle = '#c9a86a';
    ctx.fillRect(0, 2, 16, 2);
    ctx.fillRect(0, 12, 16, 2);
    ctx.fillStyle = '#8a6a3a';
    for (let y = 5; y < 11; y += 2) ctx.fillRect(3, y, 6 + ((y * 3) % 4), 1);
    ctx.fillStyle = '#b02a2a';
    ctx.fillRect(11, 8, 3, 3);
    ctx.fillStyle = '#e04a4a';
    ctx.fillRect(12, 8, 1, 1);
  });
}

export function taskBoardCanvas(): HTMLCanvasElement {
  const r = rng(77);
  return makeCanvas(48, 32, (ctx) => {
    for (let y = 0; y < 32; y++)
      for (let x = 0; x < 48; x++) {
        ctx.fillStyle = css(shade(hex('#8a5f33'), 0.9 + r() * 0.15 - (y % 8 === 7 ? 0.2 : 0)));
        ctx.fillRect(x, y, 1, 1);
      }
    ctx.fillStyle = '#4a3019';
    ctx.fillRect(0, 0, 48, 2);
    ctx.fillRect(0, 30, 48, 2);
    ctx.fillRect(0, 0, 2, 32);
    ctx.fillRect(46, 0, 2, 32);
    const papers = ['#f4ecd6', '#fff8e0', '#e8f0ff', '#ffe8e8', '#f0ffe0'];
    for (let i = 0; i < 9; i++) {
      const x = 4 + (i % 5) * 8 + Math.floor(r() * 2);
      const y = 4 + Math.floor(i / 5) * 13 + Math.floor(r() * 3);
      ctx.fillStyle = papers[Math.floor(r() * papers.length)];
      ctx.fillRect(x, y, 6, 8);
      ctx.fillStyle = '#9a8c70';
      for (let l = 0; l < 3; l++) ctx.fillRect(x + 1, y + 2 + l * 2, 3 + Math.floor(r() * 2), 1);
      ctx.fillStyle = ['#d03a3a', '#3a70d0', '#e0b020'][i % 3];
      ctx.fillRect(x + 2, y, 2, 1);
    }
  });
}
