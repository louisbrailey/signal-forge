// Pooled pixel particles, fireworks, XP orbs, poofs and flying items (scrolls / chests).
import * as THREE from 'three';
import { scrollCanvas, pixelTexture, tileUV, getAtlas } from './textures';
import { T } from './blocks';
import { rng } from './noise';

export enum P {
  Square = 0,
  Spark = 1,
  Smoke = 2,
  Page = 3,
  Rune = 4, // 4..7
  Star = 8,
  Dots = 9,
  Hourglass = 10,
  Orb = 11,
  Heart = 12,
  Swirl = 13,
  Note = 14,
  Check = 15,
}

// ---------------------------------------------------------------- particle sprite atlas (4×4 of 16px)
function particleAtlas(): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const ctx = c.getContext('2d')!;
  const r = rng(99);
  const px = (tile: number, x: number, y: number, col: string): void => {
    ctx.fillStyle = col;
    ctx.fillRect((tile % 4) * 16 + x, Math.floor(tile / 4) * 16 + y, 1, 1);
  };
  const rect = (tile: number, x: number, y: number, w: number, h: number, col: string): void => {
    ctx.fillStyle = col;
    ctx.fillRect((tile % 4) * 16 + x, Math.floor(tile / 4) * 16 + y, w, h);
  };
  // 0 square
  rect(0, 3, 3, 10, 10, '#ffffff');
  rect(0, 3, 11, 10, 2, '#cfcfcf');
  rect(0, 11, 3, 2, 10, '#dedede');
  // 1 spark (plus)
  rect(1, 6, 1, 4, 14, '#ffffff');
  rect(1, 1, 6, 14, 4, '#ffffff');
  rect(1, 5, 5, 6, 6, '#ffffff');
  // 2 smoke puff
  for (let y = 0; y < 16; y++)
    for (let x = 0; x < 16; x++) {
      const d = Math.hypot(x - 7.5, y - 7.5);
      if (d < 7 - r() * 1.5) px(2, x, y, d < 4 ? '#ffffff' : r() < 0.5 ? '#e6e6e6' : '#d0d0d0');
    }
  // 3 page
  rect(3, 3, 1, 10, 14, '#fdf6e0');
  rect(3, 3, 14, 10, 1, '#d8cba8');
  for (let y = 4; y < 13; y += 2) rect(3, 5, y, 5 + (y % 4 === 0 ? 1 : 0), 1, '#8a7d62');
  // 4..7 runes (enchanting-table-like glyphs, original shapes)
  const runes = [
    [[2, 2, 12, 2], [7, 2, 2, 12], [2, 12, 5, 2]],
    [[2, 2, 2, 12], [2, 7, 12, 2], [12, 2, 2, 6]],
    [[3, 3, 10, 2], [3, 3, 2, 10], [9, 8, 4, 2], [11, 8, 2, 6]],
    [[2, 7, 12, 2], [5, 2, 2, 5], [9, 9, 2, 5]],
  ];
  runes.forEach((rs, i) => rs.forEach(([x, y, w, h]) => rect(4 + i, x, y, w, h, '#ffffff')));
  // 8 star
  rect(8, 7, 1, 2, 14, '#ffffff');
  rect(8, 1, 7, 14, 2, '#ffffff');
  rect(8, 5, 5, 6, 6, '#ffffff');
  rect(8, 4, 4, 2, 2, '#ffffff');
  rect(8, 10, 10, 2, 2, '#ffffff');
  rect(8, 10, 4, 2, 2, '#ffffff');
  rect(8, 4, 10, 2, 2, '#ffffff');
  // 9 thought dots "…" in a bubble
  rect(9, 1, 4, 14, 8, '#ffffff');
  rect(9, 2, 3, 12, 10, '#ffffff');
  rect(9, 3, 7, 2, 2, '#555555');
  rect(9, 7, 7, 2, 2, '#555555');
  rect(9, 11, 7, 2, 2, '#555555');
  rect(9, 3, 13, 2, 2, '#ffffff');
  // 10 hourglass
  rect(10, 3, 1, 10, 2, '#8a5a2a');
  rect(10, 3, 13, 10, 2, '#8a5a2a');
  rect(10, 4, 3, 8, 2, '#e6f2ff');
  rect(10, 5, 5, 6, 2, '#e6f2ff');
  rect(10, 7, 7, 2, 2, '#e6f2ff');
  rect(10, 5, 9, 6, 2, '#e6f2ff');
  rect(10, 4, 11, 8, 2, '#f2c84b');
  rect(10, 6, 9, 4, 2, '#f2c84b');
  // 11 xp orb
  for (let y = 0; y < 16; y++)
    for (let x = 0; x < 16; x++) {
      const d = Math.hypot(x - 7.5, y - 7.5);
      if (d < 6) px(11, x, y, d < 2.5 ? '#ffffff' : d < 4.5 ? '#e8ff9a' : '#a4e03a');
    }
  // 12 heart
  const heart = ['..XX...XX..', '.XXXX.XXXX.', 'XXXXXXXXXXX', 'XXXXXXXXXXX', '.XXXXXXXXX.', '..XXXXXXX..', '...XXXXX...', '....XXX....', '.....X.....'];
  heart.forEach((row, y) => row.split('').forEach((ch, x) => ch === 'X' && px(12, x + 2, y + 3, '#ffffff')));
  // 13 swirl (portal)
  for (let i = 0; i < 40; i++) {
    const a = i * 0.45;
    const rr = 1 + i * 0.16;
    px(13, Math.round(7.5 + Math.cos(a) * rr), Math.round(7.5 + Math.sin(a) * rr), '#ffffff');
    px(13, Math.round(8 + Math.cos(a) * rr), Math.round(7.5 + Math.sin(a) * rr), '#ffffff');
  }
  // 14 note
  rect(14, 9, 2, 2, 10, '#ffffff');
  rect(14, 9, 2, 5, 2, '#ffffff');
  rect(14, 12, 4, 2, 2, '#ffffff');
  rect(14, 5, 10, 5, 4, '#ffffff');
  // 15 check
  const check = [[2, 8], [3, 9], [4, 10], [5, 11], [6, 10], [7, 9], [8, 8], [9, 7], [10, 6], [11, 5], [12, 4], [13, 3]];
  check.forEach(([x, y]) => rect(15, x, y, 2, 2, '#ffffff'));
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  tex.flipY = false;
  return tex;
}

const VERT = /* glsl */ `
attribute vec3 pcolor;
attribute float psize;
attribute float palpha;
attribute float ptile;
uniform float uScale;
varying vec3 vColor;
varying float vAlpha;
varying float vTile;
void main() {
  vColor = pcolor;
  vAlpha = palpha;
  vTile = ptile;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = max(2.0, psize * uScale / max(0.1, -mv.z));
}`;

const FRAG = /* glsl */ `
uniform sampler2D uMap;
uniform float uAdditive;
varying vec3 vColor;
varying float vAlpha;
varying float vTile;
void main() {
  vec2 cell = vec2(mod(vTile, 4.0), floor(vTile / 4.0));
  vec2 uv = (cell + gl_PointCoord) / 4.0;
  vec4 t = texture2D(uMap, uv);
  if (t.a < 0.5) discard;
  vec3 c = t.rgb * vColor;
  if (uAdditive > 0.5) gl_FragColor = vec4(c * vAlpha, 1.0);
  else gl_FragColor = vec4(c, vAlpha);
  #include <colorspace_fragment>
}`;

export interface ParticleOpts {
  pos: THREE.Vector3 | { x: number; y: number; z: number };
  vel?: { x: number; y: number; z: number };
  color?: THREE.ColorRepresentation;
  size?: number;
  sizeEnd?: number;
  life?: number;
  gravity?: number;
  drag?: number;
  tile?: number;
  /** homing target (xp orbs) */
  home?: THREE.Vector3;
  homeStrength?: number;
}

class ParticlePool {
  readonly points: THREE.Points;
  private geo = new THREE.BufferGeometry();
  private pos: Float32Array;
  private col: Float32Array;
  private size: Float32Array;
  private alpha: Float32Array;
  private tile: Float32Array;
  private vel: Float32Array;
  private life: Float32Array;
  private maxLife: Float32Array;
  private s0: Float32Array;
  private s1: Float32Array;
  private grav: Float32Array;
  private drag: Float32Array;
  private home: (THREE.Vector3 | null)[];
  private homeK: Float32Array;
  count = 0;
  readonly mat: THREE.ShaderMaterial;
  private tmp = new THREE.Color();

  constructor(readonly cap: number, map: THREE.Texture, additive: boolean) {
    this.pos = new Float32Array(cap * 3);
    this.col = new Float32Array(cap * 3);
    this.size = new Float32Array(cap);
    this.alpha = new Float32Array(cap);
    this.tile = new Float32Array(cap);
    this.vel = new Float32Array(cap * 3);
    this.life = new Float32Array(cap);
    this.maxLife = new Float32Array(cap);
    this.s0 = new Float32Array(cap);
    this.s1 = new Float32Array(cap);
    this.grav = new Float32Array(cap);
    this.drag = new Float32Array(cap);
    this.homeK = new Float32Array(cap);
    this.home = new Array(cap).fill(null);
    this.geo.setAttribute('position', new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    this.geo.setAttribute('pcolor', new THREE.BufferAttribute(this.col, 3).setUsage(THREE.DynamicDrawUsage));
    this.geo.setAttribute('psize', new THREE.BufferAttribute(this.size, 1).setUsage(THREE.DynamicDrawUsage));
    this.geo.setAttribute('palpha', new THREE.BufferAttribute(this.alpha, 1).setUsage(THREE.DynamicDrawUsage));
    this.geo.setAttribute('ptile', new THREE.BufferAttribute(this.tile, 1).setUsage(THREE.DynamicDrawUsage));
    this.geo.setDrawRange(0, 0);
    this.mat = new THREE.ShaderMaterial({
      uniforms: { uMap: { value: map }, uScale: { value: 400 }, uAdditive: { value: additive ? 1 : 0 } },
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    });
    this.points = new THREE.Points(this.geo, this.mat);
    this.points.frustumCulled = false;
    this.points.renderOrder = additive ? 11 : 10;
  }

  spawn(o: ParticleOpts): void {
    if (this.count >= this.cap) return;
    const i = this.count++;
    this.pos[i * 3] = o.pos.x;
    this.pos[i * 3 + 1] = o.pos.y;
    this.pos[i * 3 + 2] = o.pos.z;
    this.vel[i * 3] = o.vel?.x ?? 0;
    this.vel[i * 3 + 1] = o.vel?.y ?? 0;
    this.vel[i * 3 + 2] = o.vel?.z ?? 0;
    this.tmp.set(o.color ?? 0xffffff);
    this.col[i * 3] = this.tmp.r;
    this.col[i * 3 + 1] = this.tmp.g;
    this.col[i * 3 + 2] = this.tmp.b;
    this.s0[i] = o.size ?? 0.2;
    this.s1[i] = o.sizeEnd ?? this.s0[i];
    this.maxLife[i] = this.life[i] = o.life ?? 1;
    this.grav[i] = o.gravity ?? 0;
    this.drag[i] = o.drag ?? 0;
    this.tile[i] = o.tile ?? P.Square;
    this.home[i] = o.home ?? null;
    this.homeK[i] = o.homeStrength ?? 0;
    this.size[i] = this.s0[i];
    this.alpha[i] = 1;
  }

  private kill(i: number): void {
    const j = --this.count;
    if (i === j) return;
    const c3 = (a: Float32Array): void => {
      a[i * 3] = a[j * 3];
      a[i * 3 + 1] = a[j * 3 + 1];
      a[i * 3 + 2] = a[j * 3 + 2];
    };
    c3(this.pos);
    c3(this.vel);
    c3(this.col);
    for (const a of [this.size, this.alpha, this.tile, this.life, this.maxLife, this.s0, this.s1, this.grav, this.drag, this.homeK]) a[i] = a[j];
    this.home[i] = this.home[j];
  }

  update(dt: number): void {
    for (let i = 0; i < this.count; i++) {
      this.life[i] -= dt;
      if (this.life[i] <= 0) {
        this.kill(i);
        i--;
        continue;
      }
      const k = i * 3;
      const h = this.home[i];
      if (h) {
        const s = this.homeK[i];
        this.vel[k] += (h.x - this.pos[k]) * s * dt;
        this.vel[k + 1] += (h.y - this.pos[k + 1]) * s * dt;
        this.vel[k + 2] += (h.z - this.pos[k + 2]) * s * dt;
        const d = Math.hypot(h.x - this.pos[k], h.y - this.pos[k + 1], h.z - this.pos[k + 2]);
        if (d < 0.35 && this.maxLife[i] - this.life[i] > 0.4) this.life[i] = Math.min(this.life[i], 0.05);
      }
      this.vel[k + 1] -= this.grav[i] * dt;
      const dr = Math.max(0, 1 - this.drag[i] * dt);
      this.vel[k] *= dr;
      this.vel[k + 1] *= dr;
      this.vel[k + 2] *= dr;
      this.pos[k] += this.vel[k] * dt;
      this.pos[k + 1] += this.vel[k + 1] * dt;
      this.pos[k + 2] += this.vel[k + 2] * dt;
      const t = 1 - this.life[i] / this.maxLife[i];
      this.size[i] = this.s0[i] + (this.s1[i] - this.s0[i]) * t;
      this.alpha[i] = t < 0.1 ? t / 0.1 : this.life[i] < 0.3 ? this.life[i] / 0.3 : 1;
    }
    this.geo.setDrawRange(0, this.count);
    for (const name of ['position', 'pcolor', 'psize', 'palpha', 'ptile']) (this.geo.getAttribute(name) as THREE.BufferAttribute).needsUpdate = true;
  }

  dispose(): void {
    this.geo.dispose();
    this.mat.dispose();
  }
}

interface Flight {
  mesh: THREE.Object3D;
  from: THREE.Vector3;
  to: () => THREE.Vector3 | null;
  t: number;
  dur: number;
  height: number;
  trail: number; // colour
  onArrive?: () => void;
  spin: number;
}

interface Emitter {
  update(dt: number): boolean; // false = done
}

export class Effects {
  readonly group = new THREE.Group();
  private normal: ParticlePool;
  private glow: ParticlePool;
  private flights: Flight[] = [];
  private emitters: Emitter[] = [];
  private scrollGeo: THREE.BufferGeometry;
  private scrollMat: THREE.MeshBasicMaterial;
  private chestGeo: THREE.BufferGeometry;
  private chestMat: THREE.MeshBasicMaterial;
  private tex: THREE.CanvasTexture;
  density = 1;

  constructor(cap = 2400) {
    this.tex = particleAtlas();
    this.normal = new ParticlePool(Math.floor(cap * 0.5), this.tex, false);
    this.glow = new ParticlePool(Math.floor(cap * 0.5), this.tex, true);
    this.group.add(this.normal.points, this.glow.points);
    // scroll: a thin rolled parchment
    this.scrollGeo = new THREE.BoxGeometry(0.95, 0.1, 0.7);
    this.scrollMat = new THREE.MeshBasicMaterial({ map: pixelTexture(scrollCanvas()), color: new THREE.Color(1.3, 1.2, 1.4) });
    this.chestGeo = chestGeometry();
    this.chestMat = new THREE.MeshBasicMaterial({ map: getAtlas() });
  }

  setScale(pxHeight: number, fov: number): void {
    // 1.7× so pixel particles stay legible from village-overview distances
    const s = (1.7 * pxHeight) / (2 * Math.tan((fov * Math.PI) / 360));
    this.normal.mat.uniforms.uScale.value = s;
    this.glow.mat.uniforms.uScale.value = s;
  }

  private keep(): boolean {
    return this.density >= 1 || Math.random() < this.density;
  }

  /** raw spawn; glow = additive */
  spawn(o: ParticleOpts, glow = false): void {
    if (!this.keep()) return;
    (glow ? this.glow : this.normal).spawn(o);
  }

  // ------------------------------------------------------------ presets
  poof(pos: THREE.Vector3, n = 22, color: THREE.ColorRepresentation = 0xf0f0f0): void {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const s = 0.8 + Math.random() * 1.6;
      this.spawn({
        pos: { x: pos.x + Math.cos(a) * 0.3, y: pos.y + Math.random() * 1.6, z: pos.z + Math.sin(a) * 0.3 },
        vel: { x: Math.cos(a) * s, y: 0.4 + Math.random() * 0.8, z: Math.sin(a) * s },
        color: new THREE.Color(color).multiplyScalar(0.8 + Math.random() * 0.25),
        size: 0.35 + Math.random() * 0.2,
        sizeEnd: 0.1,
        life: 0.6 + Math.random() * 0.5,
        drag: 3,
        tile: P.Smoke,
      });
    }
  }

  sparks(pos: THREE.Vector3, n = 14, colors: number[] = [0xff3a2a, 0xff8a2a, 0xffd04a]): void {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const s = 1 + Math.random() * 2.2;
      this.spawn(
        {
          pos,
          vel: { x: Math.cos(a) * s * 0.6, y: 1.5 + Math.random() * 2.5, z: Math.sin(a) * s * 0.6 },
          color: colors[i % colors.length],
          size: 0.1 + Math.random() * 0.08,
          sizeEnd: 0.03,
          life: 0.5 + Math.random() * 0.4,
          gravity: 9,
          tile: i % 3 === 0 ? P.Spark : P.Square,
        },
        true,
      );
    }
  }

  pages(pos: THREE.Vector3, n = 6): void {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      this.spawn({
        pos: { x: pos.x + Math.cos(a) * 0.3, y: pos.y, z: pos.z + Math.sin(a) * 0.3 },
        vel: { x: Math.cos(a) * 0.4, y: 0.8 + Math.random() * 0.6, z: Math.sin(a) * 0.4 },
        size: 0.22,
        sizeEnd: 0.16,
        life: 1.2 + Math.random() * 0.6,
        gravity: 0.6,
        drag: 1,
        tile: P.Page,
      });
    }
    this.runes(pos, 5, 0x9fc8ff);
  }

  runes(pos: THREE.Vector3, n = 8, color: THREE.ColorRepresentation = 0xc49bff, spread = 1.2): void {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const r = spread * (0.5 + Math.random() * 0.5);
      this.spawn(
        {
          pos: { x: pos.x + Math.cos(a) * r, y: pos.y + Math.random() * 0.8, z: pos.z + Math.sin(a) * r },
          vel: { x: -Math.cos(a) * r * 0.7, y: 0.3 + Math.random() * 0.4, z: -Math.sin(a) * r * 0.7 },
          color,
          size: 0.16,
          sizeEnd: 0.08,
          life: 1 + Math.random() * 0.6,
          drag: 0.6,
          tile: P.Rune + Math.floor(Math.random() * 4),
        },
        true,
      );
    }
  }

  portal(pos: THREE.Vector3, n = 12): void {
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      this.spawn(
        {
          pos: { x: pos.x + Math.cos(a) * 0.7, y: pos.y + Math.random() * 0.4, z: pos.z + Math.sin(a) * 0.7 },
          vel: { x: -Math.sin(a) * 1.2, y: 0.5 + Math.random() * 0.4, z: Math.cos(a) * 1.2 },
          color: i % 2 ? 0xb56bff : 0x6be0ff,
          size: 0.16,
          sizeEnd: 0.05,
          life: 1 + Math.random() * 0.4,
          drag: 0.8,
          tile: i % 3 === 0 ? P.Swirl : P.Square,
        },
        true,
      );
    }
  }

  thought(pos: THREE.Vector3): void {
    this.spawn({
      pos: { x: pos.x + 0.25, y: pos.y, z: pos.z },
      vel: { x: 0.08, y: 0.45, z: 0 },
      size: 0.34,
      sizeEnd: 0.42,
      life: 1.6,
      tile: P.Dots,
    });
    for (let i = 0; i < 2; i++)
      this.spawn({
        pos: { x: pos.x + 0.1 + i * 0.08, y: pos.y - 0.25 + i * 0.12, z: pos.z },
        vel: { x: 0.05, y: 0.4, z: 0 },
        size: 0.07 + i * 0.03,
        life: 1.2,
        tile: P.Square,
      });
  }

  hourglass(pos: THREE.Vector3): void {
    this.spawn({ pos, vel: { x: 0, y: 0.35, z: 0 }, size: 0.3, sizeEnd: 0.26, life: 1.8, tile: P.Hourglass });
  }

  smoke(pos: THREE.Vector3, n = 6, color: THREE.ColorRepresentation = 0xd23a2a): void {
    for (let i = 0; i < n; i++)
      this.spawn({
        pos: { x: pos.x + (Math.random() - 0.5) * 0.5, y: pos.y + Math.random() * 0.3, z: pos.z + (Math.random() - 0.5) * 0.5 },
        vel: { x: (Math.random() - 0.5) * 0.3, y: 0.7 + Math.random() * 0.5, z: (Math.random() - 0.5) * 0.3 },
        color: new THREE.Color(color).multiplyScalar(0.6 + Math.random() * 0.5),
        size: 0.26,
        sizeEnd: 0.55,
        life: 1.4 + Math.random() * 0.6,
        drag: 0.5,
        tile: P.Smoke,
      });
  }

  sparkle(pos: THREE.Vector3, n = 10, color: THREE.ColorRepresentation = 0x7dff9a, radius = 0.7): void {
    for (let i = 0; i < n; i++)
      this.spawn(
        {
          pos: { x: pos.x + (Math.random() - 0.5) * radius * 2, y: pos.y + Math.random() * 1.5, z: pos.z + (Math.random() - 0.5) * radius * 2 },
          vel: { x: 0, y: 0.5 + Math.random() * 0.6, z: 0 },
          color,
          size: 0.14 + Math.random() * 0.1,
          sizeEnd: 0.02,
          life: 0.8 + Math.random() * 0.6,
          tile: Math.random() < 0.5 ? P.Star : P.Spark,
        },
        true,
      );
  }

  notes(pos: THREE.Vector3, color: THREE.ColorRepresentation = 0xffffff): void {
    this.spawn({ pos, vel: { x: (Math.random() - 0.5) * 0.4, y: 0.6, z: 0 }, color, size: 0.24, life: 1.4, tile: P.Note });
  }

  check(pos: THREE.Vector3): void {
    this.spawn({ pos, vel: { x: 0, y: 0.5, z: 0 }, color: 0x5dff7a, size: 0.4, sizeEnd: 0.3, life: 1.5, tile: P.Check }, true);
  }

  blockBreak(pos: THREE.Vector3, tint: THREE.ColorRepresentation = 0xb08853): void {
    for (let i = 0; i < 8; i++)
      this.spawn({
        pos: { x: pos.x + (Math.random() - 0.5) * 0.9, y: pos.y + (Math.random() - 0.5) * 0.9, z: pos.z + (Math.random() - 0.5) * 0.9 },
        vel: { x: (Math.random() - 0.5) * 2, y: 1.5 + Math.random() * 1.5, z: (Math.random() - 0.5) * 2 },
        color: new THREE.Color(tint).multiplyScalar(0.7 + Math.random() * 0.4),
        size: 0.1,
        life: 0.6 + Math.random() * 0.3,
        gravity: 12,
        tile: P.Square,
      });
  }

  xpOrbs(from: THREE.Vector3, to: THREE.Vector3, n = 10): void {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      this.spawn(
        {
          pos: { x: from.x + Math.cos(a) * 1.2, y: from.y + Math.random() * 1.2, z: from.z + Math.sin(a) * 1.2 },
          vel: { x: Math.cos(a) * 2, y: 2 + Math.random() * 2, z: Math.sin(a) * 2 },
          color: Math.random() < 0.5 ? 0xd4ff5a : 0x9aff3a,
          size: 0.22,
          sizeEnd: 0.16,
          life: 2.4,
          gravity: 2,
          drag: 1.4,
          tile: P.Orb,
          home: to,
          homeStrength: 14,
        },
        true,
      );
    }
  }

  firework(pos: THREE.Vector3, palette?: number[]): void {
    const cols = palette ?? [
      [0xff4a6a, 0xffd04a],
      [0x5ad0ff, 0xffffff],
      [0x7dff7a, 0xf2ff5a],
      [0xc36bff, 0xff9ae0],
    ][Math.floor(Math.random() * 4)];
    const p = pos.clone();
    const v = new THREE.Vector3((Math.random() - 0.5) * 0.8, 11 + Math.random() * 3, (Math.random() - 0.5) * 0.8);
    let t = 0;
    const fuse = 0.75 + Math.random() * 0.25;
    this.emitters.push({
      update: (dt) => {
        t += dt;
        v.y -= 9 * dt;
        p.addScaledVector(v, dt);
        this.spawn({ pos: p, vel: { x: (Math.random() - 0.5) * 0.3, y: -0.5, z: (Math.random() - 0.5) * 0.3 }, color: 0xffe0a0, size: 0.09, life: 0.5, tile: P.Spark }, true);
        if (t >= fuse) {
          const n = 90;
          for (let i = 0; i < n; i++) {
            const u = Math.random() * 2 - 1;
            const a = Math.random() * Math.PI * 2;
            const s = Math.sqrt(1 - u * u);
            const sp = 5 + Math.random() * 1.5;
            this.spawn(
              {
                pos: p,
                vel: { x: s * Math.cos(a) * sp, y: u * sp, z: s * Math.sin(a) * sp },
                color: cols[i % cols.length],
                size: 0.2,
                sizeEnd: 0.05,
                life: 1.1 + Math.random() * 0.6,
                gravity: 2.5,
                drag: 1.8,
                tile: i % 4 === 0 ? P.Star : P.Spark,
              },
              true,
            );
          }
          return false;
        }
        return true;
      },
    });
  }

  /** run a callback repeatedly for `dur` seconds (e.g. a trail) */
  over(dur: number, every: number, fn: () => void): void {
    let t = 0;
    let acc = 0;
    this.emitters.push({
      update: (dt) => {
        t += dt;
        acc += dt;
        while (acc >= every) {
          acc -= every;
          fn();
        }
        return t < dur;
      },
    });
  }

  // ------------------------------------------------------------ flying items
  flyScroll(from: THREE.Vector3, to: () => THREE.Vector3 | null, onArrive?: () => void): void {
    const m = new THREE.Mesh(this.scrollGeo, this.scrollMat);
    this.fly(m, from, to, 0xc07bff, 1.7, onArrive);
  }

  flyChest(from: THREE.Vector3, to: () => THREE.Vector3 | null, onArrive?: () => void): void {
    const m = new THREE.Mesh(this.chestGeo, this.chestMat);
    this.fly(m, from, to, 0xffd04a, 1.6, onArrive);
  }

  private fly(mesh: THREE.Object3D, from: THREE.Vector3, to: () => THREE.Vector3 | null, trail: number, dur: number, onArrive?: () => void): void {
    mesh.position.copy(from);
    this.group.add(mesh);
    const end = to();
    const dist = end ? end.distanceTo(from) : 10;
    this.flights.push({ mesh, from: from.clone(), to, t: 0, dur: dur * Math.min(1.6, Math.max(0.7, dist / 25)), height: 3 + dist * 0.28, trail, onArrive, spin: Math.random() < 0.5 ? 1 : -1 });
  }

  update(dt: number, t: number): void {
    for (let i = this.emitters.length - 1; i >= 0; i--) if (!this.emitters[i].update(dt)) this.emitters.splice(i, 1);
    for (let i = this.flights.length - 1; i >= 0; i--) {
      const f = this.flights[i];
      f.t += dt / f.dur;
      const end = f.to();
      if (!end) {
        this.group.remove(f.mesh);
        this.flights.splice(i, 1);
        continue;
      }
      const k = Math.min(1, f.t);
      const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      // quadratic bezier with a high control point
      const cx = (f.from.x + end.x) / 2;
      const cz = (f.from.z + end.z) / 2;
      const cy = Math.max(f.from.y, end.y) + f.height;
      const u = 1 - e;
      const x = u * u * f.from.x + 2 * u * e * cx + e * e * end.x;
      const y = u * u * f.from.y + 2 * u * e * cy + e * e * end.y;
      const z = u * u * f.from.z + 2 * u * e * cz + e * e * end.z;
      f.mesh.position.set(x, y + Math.sin(t * 8) * 0.05, z);
      f.mesh.rotation.y += dt * 4 * f.spin;
      f.mesh.rotation.z = Math.sin(t * 5) * 0.3;
      this.spawn(
        {
          pos: f.mesh.position,
          vel: { x: (Math.random() - 0.5) * 0.4, y: (Math.random() - 0.5) * 0.4, z: (Math.random() - 0.5) * 0.4 },
          color: f.trail,
          size: 0.16,
          sizeEnd: 0.03,
          life: 0.7,
          tile: Math.random() < 0.3 ? P.Rune + Math.floor(Math.random() * 4) : P.Square,
        },
        true,
      );
      if (f.t >= 1) {
        this.group.remove(f.mesh);
        this.flights.splice(i, 1);
        this.sparkle(end, 12, f.trail, 0.4);
        f.onArrive?.();
      }
    }
    this.normal.update(dt);
    this.glow.update(dt);
  }

  get particleCount(): number {
    return this.normal.count + this.glow.count;
  }

  dispose(): void {
    this.normal.dispose();
    this.glow.dispose();
    this.scrollGeo.dispose();
    this.scrollMat.map?.dispose();
    this.scrollMat.dispose();
    this.chestGeo.dispose();
    this.chestMat.dispose();
    this.tex.dispose();
  }
}

function chestGeometry(): THREE.BufferGeometry {
  const g = new THREE.BoxGeometry(0.75, 0.68, 0.75);
  const uv = g.getAttribute('uv') as THREE.BufferAttribute;
  const tiles = [T.ChestSide, T.ChestSide, T.ChestTop, T.ChestTop, T.ChestFront, T.ChestSide];
  for (let f = 0; f < 6; f++) {
    const [u0, v0, u1, v1] = tileUV(tiles[f]);
    for (let i = 0; i < 4; i++) {
      const k = f * 4 + i;
      uv.setXY(k, u0 + uv.getX(k) * (u1 - u0), v0 + (1 - uv.getY(k)) * (v1 - v0));
    }
  }
  return g;
}
