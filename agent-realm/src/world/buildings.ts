// Council Hall, village decor, task board and per-worker plots (workshop + growing build site).
import * as THREE from 'three';
import { B } from './blocks';
import { meshBlocks } from './mesher';
import { hash3, hashString } from './noise';
import {
  HALL, HALL_Y, PLAZA, VILLAGE_Y, TABLE_R, PLOT_HALF, type PlotSlot,
} from './layout';
import { bannerCanvas, getAtlas, pixelTexture, taskBoardCanvas, tileUV } from './textures';
import { worldMaterials, type VoxelWorld } from './terrain';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { T } from './blocks';
import type { AgentSource, MissionStatus } from '../../shared/protocol';

const S = HALL_Y + 1; // standing height in the hall

// ---------------------------------------------------------------- geometry helpers
/** Box whose faces sample a single atlas tile, at 16px-per-block pixel density. */
export function tiledBox(w: number, h: number, d: number, tile: number | number[]): THREE.BufferGeometry {
  const g = new THREE.BoxGeometry(w, h, d);
  const uv = g.getAttribute('uv') as THREE.BufferAttribute;
  const sizes: [number, number][] = [
    [d, h], [d, h], [w, d], [w, d], [w, h], [w, h],
  ];
  for (let f = 0; f < 6; f++) {
    const t = Array.isArray(tile) ? tile[f] : tile;
    const [u0, v0, u1, v1] = tileUV(t);
    const [fw, fh] = sizes[f];
    const su = Math.min(1, fw);
    const sv = Math.min(1, fh);
    for (let i = 0; i < 4; i++) {
      const k = f * 4 + i;
      const u = uv.getX(k);
      const v = uv.getY(k);
      uv.setXY(k, u0 + u * su * (u1 - u0), v0 + (1 - v) * sv * (v1 - v0));
    }
  }
  return g;
}

// ---------------------------------------------------------------- static voxel stamps
function hallDist(x: number, z: number): number {
  return Math.hypot(x + 0.5 - HALL.x, z + 0.5 - HALL.z);
}

export const PILLAR_ANGLES = Array.from({ length: 8 }, (_, k) => ((k * 45 + 22.5) * Math.PI) / 180);

export function stampCouncilHall(v: VoxelWorld): void {
  const F = HALL_Y;
  const R = 10.6;
  for (let x = HALL.x - 12; x <= HALL.x + 12; x++)
    for (let z = HALL.z - 12; z <= HALL.z + 12; z++) {
      const d = hallDist(x, z);
      if (d > R) continue;
      v.reserve(x, z);
      for (let y = F - 4; y < F; y++) if (v.get(x, y, z) === 0 || d > R - 1) v.set(x, y, z, d > R - 1 ? B.Cobble : B.Stone);
      for (let y = F + 1; y < F + 14; y++) v.set(x, y, z, 0);
      let id: number;
      if (d <= 2.9) id = B.Obsidian;
      else if (d <= 5.2) id = B.PurpleWool;
      else if (d <= 6.3) id = B.GoldTrim;
      else if (d <= 8.4) id = (Math.floor(Math.atan2(z + 0.5 - HALL.z, x + 0.5 - HALL.x) / (Math.PI / 8)) & 1) ? B.SmoothStone : B.Quartz;
      else if (d <= R - 1) id = hash3(x, F, z, 2) < 0.15 ? B.MossyBricks : B.StoneBricks;
      else id = hash3(x, F, z, 3) < 0.25 ? B.MossyCobble : B.Cobble;
      v.set(x, F, z, id);
      // round table
      if (d <= TABLE_R) v.set(x, S, z, B.Enchant);
      // rim wall with south entrance + bookshelves to the north
      if (d > R - 1) {
        const south = z > HALL.z && Math.abs(x + 0.5 - HALL.x) < 3;
        if (!south) {
          const north = z + 0.5 < HALL.z - 6;
          v.set(x, S, z, north ? B.Bookshelf : B.StoneBricks);
          if (north && Math.abs(x + 0.5) > 1.5) v.set(x, S + 1, z, B.Bookshelf);
        }
      }
      // roof ring (open oculus so the council is visible from above)
      if (d > 7.9) {
        v.set(x, S + 6, z, d > R - 0.9 ? B.StoneBricks : d <= 8.8 ? B.DarkLog : B.DarkPlanks);
        if (d > R - 0.9 && (x + z) % 2 === 0) v.set(x, S + 7, z, B.StoneBricks);
      }
    }
  // pillars
  PILLAR_ANGLES.forEach((a, k) => {
    const x = Math.floor(HALL.x + Math.cos(a) * 9.1);
    const z = Math.floor(HALL.z + Math.sin(a) * 9.1);
    v.set(x, S, z, B.StoneBricks);
    for (let y = S + 1; y <= S + 4; y++) v.set(x, y, z, B.DarkLog);
    v.set(x, S + 5, z, B.GoldTrim);
    if (k % 2 === 0) {
      // turrets
      for (let y = S + 7; y <= S + 8; y++) v.set(x, y, z, B.StoneBricks);
      v.set(x, S + 9, z, B.GoldTrim);
      v.set(x, S + 10, z, B.Lantern);
    }
  });
  // hanging lanterns between pillars
  for (let k = 0; k < 8; k++) {
    const a = (k * 45 * Math.PI) / 180;
    const x = Math.floor(HALL.x + Math.cos(a) * 8.4);
    const z = Math.floor(HALL.z + Math.sin(a) * 8.4);
    if (v.get(x, S + 6, z) !== 0) v.set(x, S + 5, z, B.Lantern);
  }
  // steps down the entrance
  for (let x = -2; x <= 2; x++) v.set(x, F, HALL.z + 11, B.StoneBricks);
}

export function stampVillage(v: VoxelWorld): void {
  const y = VILLAGE_Y + 1;
  const post = (x: number, z: number, base = v.surf(x, z) + 1): void => {
    v.set(x, base, z, B.Cobble); // voxel foot (blocks walking); the slim post + lantern are meshes
    let flat = true;
    for (let dx = -3; dx <= 3; dx++) for (let dz = -3; dz <= 3; dz++) if (v.surf(x + dx, z + dz) !== base - 1) flat = false;
    LAMPS.push({ x, y: base + 1, z, flat });
    v.reserve(x, z);
  };
  LAMPS.length = 0;
  // plaza lamp posts
  post(PLAZA.x - 4, PLAZA.z + 3);
  post(PLAZA.x + 3, PLAZA.z + 3);
  post(PLAZA.x - 4, PLAZA.z - 4);
  post(PLAZA.x + 3, PLAZA.z - 4);
  // along the hall ramp
  for (const z of [-3, -9]) {
    post(-4, z);
    post(3, z);
  }
  // street lamps in the gaps between plots
  for (const x of [13, 21, 29]) for (const sx of [-x, x]) post(sx, 5);
  for (const x of [9, 17, 25]) for (const sx of [-x, x]) post(sx, 15);
  for (const x of [9, 17]) for (const sx of [-x, x]) post(sx, 25);
  // plaza props
  const prop = (x: number, z: number, id: number, stack = 1): void => {
    for (let i = 0; i < stack; i++) v.set(x, y + i, z, id);
    v.reserve(x, z);
  };
  prop(PLAZA.x + 5, PLAZA.z + 5, B.Barrel);
  prop(PLAZA.x + 6, PLAZA.z + 4, B.Hay, 2);
  prop(PLAZA.x + 6, PLAZA.z + 5, B.Hay);
  prop(PLAZA.x - 6, PLAZA.z + 4, B.Barrel, 2);
  prop(PLAZA.x - 6, PLAZA.z + 5, B.Chest);
}

/** lamp post positions (top of their cobble foot), filled by stampVillage */
export const LAMPS: { x: number; y: number; z: number; flat: boolean }[] = [];

export function makeLamps(): THREE.Group {
  const g = new THREE.Group();
  const mats = worldMaterials();
  const posts: THREE.BufferGeometry[] = [];
  const glows: THREE.BufferGeometry[] = [];
  for (const l of LAMPS) {
    const cx = l.x + 0.5;
    const cz = l.z + 0.5;
    posts.push(tiledBox(0.24, 1.7, 0.24, T.DarkLog).translate(cx, l.y + 0.85, cz));
    posts.push(tiledBox(0.56, 0.12, 0.56, T.DarkPlanks).translate(cx, l.y + 2.34, cz));
    posts.push(tiledBox(0.3, 0.1, 0.3, T.DarkPlanks).translate(cx, l.y + 2.45, cz));
    glows.push(tiledBox(0.44, 0.58, 0.44, T.Lantern).translate(cx, l.y + 1.99, cz));
  }
  const pg = mergeGeometries(posts, false);
  const gg = mergeGeometries(glows, false);
  posts.forEach((x) => x.dispose());
  glows.forEach((x) => x.dispose());
  if (pg) {
    const m = new THREE.Mesh(pg, mats.solid);
    addWhiteColors(m);
    m.castShadow = true;
    m.receiveShadow = true;
    g.add(m);
  }
  if (gg) g.add(new THREE.Mesh(gg, mats.glow));
  // stepped "block light" pools on the ground, faded in at night
  const pools: THREE.BufferGeometry[] = [];
  for (const l of LAMPS) {
    if (!l.flat) continue;
    const q = new THREE.PlaneGeometry(7, 7).rotateX(-Math.PI / 2);
    q.translate(l.x + 0.5, l.y - 1 + 0.03, l.z + 0.5);
    pools.push(q);
  }
  const poolGeo = mergeGeometries(pools, false);
  pools.forEach((x) => x.dispose());
  if (poolGeo) {
    const pm = new THREE.Mesh(
      poolGeo,
      new THREE.MeshBasicMaterial({
        map: lightPoolTexture(),
        color: 0xffb060,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        polygonOffset: true,
        polygonOffsetFactor: -2,
        polygonOffsetUnits: -4,
      }),
    );
    pm.name = 'pools';
    pm.renderOrder = 3;
    g.add(pm);
  }
  return g;
}

function lightPoolTexture(): THREE.Texture {
  const c = document.createElement('canvas');
  c.width = c.height = 14;
  const ctx = c.getContext('2d')!;
  for (let y = 0; y < 14; y++)
    for (let x = 0; x < 14; x++) {
      const d = Math.abs(x - 6.5) + Math.abs(y - 6.5); // manhattan, like block light
      const level = Math.max(0, 7 - Math.floor(d)) / 7;
      const v = Math.round(255 * Math.pow(level, 1.6));
      ctx.fillStyle = `rgb(${v},${v},${v})`;
      ctx.fillRect(x, y, 1, 1);
    }
  const t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.NearestFilter;
  t.minFilter = THREE.LinearFilter;
  t.generateMipmaps = false;
  return t;
}

// ---------------------------------------------------------------- task board
export function makeTaskBoard(): THREE.Group {
  const g = new THREE.Group();
  const mats = worldMaterials();
  const postGeo = tiledBox(0.25, 2.6, 0.25, T.DarkLog);
  for (const sx of [-1.4, 1.4]) {
    const p = new THREE.Mesh(postGeo, mats.solid);
    p.position.set(sx, 1.3, 0);
    p.castShadow = true;
    g.add(p);
  }
  const frame = new THREE.Mesh(tiledBox(3.1, 2.1, 0.2, T.DarkPlanks), mats.solid);
  frame.position.set(0, 1.75, 0);
  frame.castShadow = true;
  g.add(frame);
  const faceMat = new THREE.MeshLambertMaterial({ map: pixelTexture(taskBoardCanvas()) });
  const face = new THREE.Mesh(new THREE.PlaneGeometry(2.9, 1.9), faceMat);
  face.position.set(0, 1.75, 0.105);
  g.add(face);
  const back = face.clone();
  back.rotation.y = Math.PI;
  back.position.z = -0.105;
  g.add(back);
  const roof = new THREE.Mesh(tiledBox(3.6, 0.25, 0.8, T.DarkPlanks), mats.solid);
  roof.position.set(0, 2.9, 0);
  roof.castShadow = true;
  g.add(roof);
  g.traverse((o) => ((o as THREE.Mesh).isMesh ? ((o as THREE.Mesh).receiveShadow = true) : undefined));
  // a small colour-less vertex colour attribute for the tiled boxes (world material uses vertex colours)
  g.traverse((o) => addWhiteColors(o));
  g.position.set(PLAZA.x + 0.5, VILLAGE_Y + 1, PLAZA.z - 0.5);
  return g;
}

export function addWhiteColors(o: THREE.Object3D): void {
  const m = o as THREE.Mesh;
  if (!m.isMesh) return;
  const geo = m.geometry;
  if (geo.getAttribute('color')) return;
  const n = geo.getAttribute('position').count;
  const nor = geo.getAttribute('normal');
  const col = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const ny = nor ? nor.getY(i) : 1;
    const nx = nor ? Math.abs(nor.getX(i)) : 0;
    const l = ny > 0.5 ? 1 : ny < -0.5 ? 0.6 : nx > 0.5 ? 0.82 : 0.9;
    col[i * 3] = col[i * 3 + 1] = col[i * 3 + 2] = l;
  }
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
}

// ---------------------------------------------------------------- council hall (dynamic)
const MISSION_COLORS: Record<string, number> = {
  convening: 0x9fd8ff,
  deliberating: 0xc07bff,
  planning: 0xffcc4a,
  executing: 0x6dff9a,
  reviewing: 0x5fe8ff,
  failed: 0xff4a4a,
  idle: 0xb48cff,
};

export class CouncilHallFx {
  readonly group = new THREE.Group();
  readonly crystalLight: THREE.PointLight;
  readonly lanternLights: THREE.PointLight[] = [];
  private banners: THREE.Mesh[] = [];
  private book = new THREE.Group();
  private bookL: THREE.Mesh;
  private bookR: THREE.Mesh;
  private crystal: THREE.Mesh;
  private crystalMat: THREE.MeshLambertMaterial;
  private beam: THREE.Mesh;
  private beamOuter: THREE.Mesh;
  private beamMat: THREE.MeshBasicMaterial;
  private beamOuterMat: THREE.MeshBasicMaterial;
  private color = new THREE.Color(MISSION_COLORS.idle);
  private targetColor = new THREE.Color(MISSION_COLORS.idle);
  private activity = 0; // 0..1 smoothed
  private targetActivity = 0;
  readonly center = new THREE.Vector3(HALL.x, S, HALL.z);

  constructor() {
    // banners hang from the outer roof edge, between pillars
    const purple = pixelTexture(bannerCanvas('#6a2fa0', '#f2c83a'));
    const gold = pixelTexture(bannerCanvas('#e0a92a', '#5a2590'));
    const bGeo = new THREE.PlaneGeometry(1, 2);
    bGeo.translate(0, -1, 0);
    for (let k = 0; k < 8; k++) {
      const a = (k * 45 * Math.PI) / 180;
      const mat = new THREE.MeshLambertMaterial({ map: k % 2 ? gold : purple, side: THREE.DoubleSide, alphaTest: 0.5 });
      const m = new THREE.Mesh(bGeo, mat);
      const r = 10.72;
      m.position.set(HALL.x + Math.cos(a) * r, S + 6, HALL.z + Math.sin(a) * r);
      m.rotation.y = Math.atan2(Math.cos(a), Math.sin(a));
      m.castShadow = true;
      this.banners.push(m);
      this.group.add(m);
    }
    // floating book
    const coverMat = new THREE.MeshLambertMaterial({ color: 0x6b2d1c });
    const pageMat = new THREE.MeshLambertMaterial({ color: 0xf3ead2 });
    const half = (): THREE.Mesh => {
      const cover = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.03, 0.5), coverMat);
      cover.position.x = 0.18;
      const pages = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.05, 0.44), pageMat);
      pages.position.set(0.17, 0.035, 0);
      cover.add(pages);
      const pivot = new THREE.Mesh();
      pivot.add(cover);
      return pivot;
    };
    this.bookL = half();
    this.bookR = half();
    this.bookR.rotation.y = Math.PI;
    this.book.add(this.bookL, this.bookR);
    this.book.position.set(HALL.x, S + 1.55, HALL.z);
    this.group.add(this.book);
    // crystal
    this.crystalMat = new THREE.MeshLambertMaterial({
      color: 0xd9c2ff,
      emissive: new THREE.Color(MISSION_COLORS.idle),
      emissiveIntensity: 0.6,
      flatShading: true,
      transparent: true,
      opacity: 0.92,
    });
    this.crystal = new THREE.Mesh(new THREE.OctahedronGeometry(0.42, 0), this.crystalMat);
    this.crystal.scale.set(1, 1.6, 1);
    this.crystal.position.set(HALL.x, S + 3.1, HALL.z);
    this.group.add(this.crystal);
    // beacon beam
    this.beamMat = new THREE.MeshBasicMaterial({
      color: this.color,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.beamOuterMat = this.beamMat.clone();
    const beamGeo = new THREE.BoxGeometry(0.34, 90, 0.34);
    beamGeo.translate(0, 45, 0);
    this.beam = new THREE.Mesh(beamGeo, this.beamMat);
    this.beam.position.copy(this.crystal.position);
    const outerGeo = new THREE.BoxGeometry(0.8, 90, 0.8);
    outerGeo.translate(0, 45, 0);
    this.beamOuter = new THREE.Mesh(outerGeo, this.beamOuterMat);
    this.beamOuter.position.copy(this.crystal.position);
    this.beam.frustumCulled = this.beamOuter.frustumCulled = false;
    this.beam.renderOrder = this.beamOuter.renderOrder = 5;
    this.group.add(this.beam, this.beamOuter);
    // lights
    this.crystalLight = new THREE.PointLight(MISSION_COLORS.idle, 6, 14, 1.6);
    this.crystalLight.position.set(HALL.x, S + 3.2, HALL.z);
    this.group.add(this.crystalLight);
    for (const a of [Math.PI * 0.25, Math.PI * 1.25]) {
      const l = new THREE.PointLight(0xffb45a, 8, 16, 1.6);
      l.position.set(HALL.x + Math.cos(a) * 7.2, S + 4.4, HALL.z + Math.sin(a) * 7.2);
      this.lanternLights.push(l);
      this.group.add(l);
    }
  }

  setMission(status: MissionStatus | null): void {
    const active = status !== null && status !== 'complete' && status !== 'cancelled';
    this.targetActivity = active ? (status === 'deliberating' || status === 'planning' || status === 'convening' ? 1 : 0.6) : 0;
    this.targetColor.set(MISSION_COLORS[active && status ? status : 'idle'] ?? MISSION_COLORS.idle);
  }

  /** mission activity 0..1 (for ambient particles) */
  get level(): number {
    return this.activity;
  }
  get tint(): THREE.Color {
    return this.color;
  }
  get crystalPos(): THREE.Vector3 {
    return this.crystal.position;
  }

  update(dt: number, t: number, night: number): void {
    const k = 1 - Math.exp(-dt * 2);
    this.activity += (this.targetActivity - this.activity) * k;
    this.color.lerp(this.targetColor, k);
    const act = this.activity;
    // book: bob + flap
    this.book.position.y = S + 1.55 + Math.sin(t * 1.6) * 0.08;
    this.book.rotation.y = t * (0.4 + act * 0.8);
    const open = 0.35 + Math.sin(t * (1.2 + act * 4)) * (0.15 + act * 0.25);
    this.bookL.rotation.z = open;
    this.bookR.rotation.z = open;
    // crystal
    this.crystal.rotation.y = t * (0.6 + act * 2.5);
    this.crystal.position.y = S + 3.1 + Math.sin(t * 1.1) * 0.12;
    this.crystalMat.emissive.copy(this.color);
    this.crystalMat.emissiveIntensity = 0.5 + act * 1.6 + Math.sin(t * 3) * 0.1 * act;
    this.beam.position.y = this.beamOuter.position.y = this.crystal.position.y;
    this.beamMat.color.copy(this.color);
    this.beamOuterMat.color.copy(this.color);
    this.beamMat.opacity = act * (0.55 + Math.sin(t * 5) * 0.06);
    this.beamOuterMat.opacity = act * 0.18;
    this.beam.visible = this.beamOuter.visible = act > 0.02;
    this.crystalLight.color.copy(this.color);
    this.crystalLight.intensity = 3 + act * 14 + night * 4;
    // lanterns flicker; stronger at night
    this.lanternLights.forEach((l, i) => {
      const f = 0.85 + Math.sin(t * 13 + i * 3) * 0.06 + Math.sin(t * 29 + i) * 0.05;
      l.intensity = (2 + night * 12) * f;
    });
    // banners sway
    this.banners.forEach((b, i) => {
      b.rotation.x = Math.sin(t * 1.3 + i * 0.9) * 0.08;
    });
  }

  dispose(): void {
    this.group.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) {
        m.geometry.dispose();
        const mat = m.material as THREE.Material & { map?: THREE.Texture | null };
        mat.map?.dispose();
        mat.dispose();
      }
    });
  }
}

// ---------------------------------------------------------------- worker plots
const STATIONS: Record<AgentSource, [number, number]> = {
  'claude-code': [B.Crafting, B.Bookshelf],
  codex: [B.Furnace, B.Chest],
  'gemini-cli': [B.Lectern, B.Bookshelf],
  aider: [B.Anvil, B.Barrel],
  cursor: [B.Lectern, B.Chest],
  ollama: [B.Hay, B.Barrel],
  copilot: [B.Anvil, B.Chest],
  opencode: [B.Crafting, B.Chest],
  goose: [B.Hay, B.Furnace],
  api: [B.Enchant, B.Bookshelf],
  demo: [B.Crafting, B.Chest],
  other: [B.Barrel, B.Chest],
};

const PALETTES: { floor: number; edge: number; wall: number; corner: number; roof: number; window: number }[] = [
  { floor: B.OakPlanks, edge: B.Cobble, wall: B.OakPlanks, corner: B.OakLog, roof: B.DarkPlanks, window: B.Glass },
  { floor: B.SmoothStone, edge: B.StoneBricks, wall: B.Bricks, corner: B.StoneBricks, roof: B.DarkPlanks, window: B.Glass },
  { floor: B.OakPlanks, edge: B.MossyCobble, wall: B.WhiteWool, corner: B.DarkLog, roof: B.RedWool, window: B.Glass },
  { floor: B.Quartz, edge: B.Quartz, wall: B.Quartz, corner: B.GoldTrim, roof: B.PurpleWool, window: B.Glass },
  { floor: B.DarkPlanks, edge: B.Cobble, wall: B.DarkPlanks, corner: B.OakLog, roof: B.Hay, window: B.Glass },
];

interface BuildStep {
  a: number;
  b: number;
  y: number;
  id: number;
}

function buildPattern(seed: number): BuildStep[] {
  const P = PALETTES[seed % PALETTES.length];
  const steps: BuildStep[] = [];
  const ring = (i: number, j: number): boolean => i === 0 || i === 3 || j === 0 || j === 3;
  const corner = (i: number, j: number): boolean => (i === 0 || i === 3) && (j === 0 || j === 3);
  // local build area: a ∈ [0,3], b ∈ [-3,0]; j=3 is the front row (b=0)
  for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) steps.push({ a: i, b: j - 3, y: 0, id: ring(i, j) ? P.edge : P.floor });
  for (let y = 1; y <= 3; y++)
    for (let j = 0; j < 4; j++)
      for (let i = 0; i < 4; i++) {
        if (!ring(i, j)) continue;
        if (y < 3 && i === 1 && j === 3) continue; // door
        let id = corner(i, j) ? P.corner : P.wall;
        if (y === 2 && !corner(i, j) && (i === 0 || i === 3) ) id = P.window;
        if (y === 2 && !corner(i, j) && j === 0 && i === 2) id = P.window;
        steps.push({ a: i, b: j - 3, y, id });
      }
  const roof: BuildStep[] = [];
  for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) roof.push({ a: i, b: j - 3, y: 4, id: ring(i, j) ? P.roof : P.corner });
  // 16+11+11+12 = 50 → 14 roof blocks (skip two front corners) = 64
  for (const r of roof) if (!(r.b === 0 && (r.a === 0 || r.a === 3))) steps.push(r);
  return steps.slice(0, 64);
}

export const BUILD_MAX = 64;

export class Plot {
  readonly group = new THREE.Group();
  private propsMesh: THREE.Group | null = null;
  private buildMesh: THREE.Group | null = null;
  private pop: { mesh: THREE.Mesh; t: number } | null = null;
  private pattern: BuildStep[];
  private placed = 0;
  private baseY: number;
  private borderMat: THREE.Material | null = null;

  constructor(
    readonly slot: PlotSlot,
    private vox: VoxelWorld,
    readonly agentId: string,
    source: AgentSource,
    initialBlocks = 0,
  ) {
    this.baseY = vox.surf(slot.cx, slot.cz) + 1;
    this.pattern = buildPattern(hashString(agentId));
    this.buildProps(source);
    this.placed = Math.min(initialBlocks, BUILD_MAX - 1);
    this.rebuild();
  }

  /**
   * Plot interiors are laid out in world axes (not plot facing) so that, from the default
   * south-facing cameras, the worker always stands in front of their workshop and build site:
   * build site = north-east 4×4, stations along the north-west, worker on the south side facing north.
   * a = +x offset, b = +z offset from the plot centre block.
   */
  cell(a: number, b: number): [number, number] {
    return [this.slot.cx + Math.floor(a), this.slot.cz + Math.floor(b)];
  }

  /** world position (centre of block) for local coords */
  world(a: number, b: number, y = 0): THREE.Vector3 {
    return new THREE.Vector3(this.slot.cx + a + 0.5, this.baseY + y, this.slot.cz + b + 0.5);
  }

  /** where the worker stands, and which way they face (toward the stations) */
  get home(): { x: number; z: number; yaw: number } {
    const p = this.world(-1.5, 0.7);
    return { x: p.x, z: p.z, yaw: Math.PI };
  }
  get stationPos(): THREE.Vector3 {
    return this.world(-2, -1, 1.1);
  }
  get secondaryPos(): THREE.Vector3 {
    return this.world(-1, -1, 1.1);
  }
  /** world point where the next block will go (for effects / facing) */
  get buildFocus(): THREE.Vector3 {
    const s = this.pattern[Math.min(this.placed, BUILD_MAX - 1)];
    return this.world(s.a, s.b, s.y + 0.5);
  }
  get count(): number {
    return this.placed;
  }

  private buildProps(source: AgentSource): void {
    const [primary, secondary] = STATIONS[source] ?? STATIONS.other;
    const blocks = new Map<string, number>();
    const key = (x: number, y: number, z: number): string => `${x},${y},${z}`;
    const add = (a: number, b: number, y: number, id: number): void => {
      const [x, z] = this.cell(a, b);
      blocks.set(key(x, this.baseY + y, z), id);
      this.vox.blocked.add(this.vox.col(x, z));
    };
    add(-2, -1, 0, primary);
    add(-1, -1, 0, secondary);
    add(-3, -1, 0, B.Barrel);
    add(-3, -1, 1, B.Lantern);
    // block the build footprint for pathing
    for (let a = 0; a <= 3; a++)
      for (let b = -3; b <= 0; b++) {
        const [x, z] = this.cell(a, b);
        this.vox.blocked.add(this.vox.col(x, z));
      }
    const positions: [number, number, number][] = [...blocks.keys()].map((k) => k.split(',').map(Number) as [number, number, number]);
    const get = (x: number, y: number, z: number): number => blocks.get(key(x, y, z)) ?? this.vox.get(x, y, z);
    const data = meshBlocks(positions, get, { skipBottom: true, facing: () => 0 });
    this.propsMesh = groupFrom(data);
    this.group.add(this.propsMesh);
    // a low fence on the west, north and east sides (open to the south), and a path border
    const mats = worldMaterials();
    const fence: THREE.BufferGeometry[] = [];
    const x0 = this.slot.cx - PLOT_HALF - 0.4;
    const x1 = this.slot.cx + PLOT_HALF + 1.4;
    const z0 = this.slot.cz - PLOT_HALF - 0.4;
    const z1 = this.slot.cz + PLOT_HALF + 1.4;
    const y0 = this.baseY;
    const post = (x: number, z: number): void => {
      fence.push(tiledBox(0.22, 1.0, 0.22, T.OakPlanks).translate(x, y0 + 0.5, z));
    };
    const rail = (xa: number, za: number, xb: number, zb: number): void => {
      const len = Math.hypot(xb - xa, zb - za);
      for (const h of [0.42, 0.8]) {
        const g = tiledBox(xa === xb ? 0.1 : len, 0.12, xa === xb ? len : 0.1, T.OakPlanks);
        g.translate((xa + xb) / 2, y0 + h, (za + zb) / 2);
        fence.push(g);
      }
    };
    const span = (xa: number, za: number, xb: number, zb: number): void => {
      const n = Math.max(1, Math.round(Math.hypot(xb - xa, zb - za) / 2.4));
      for (let i = 0; i <= n; i++) post(xa + ((xb - xa) * i) / n, za + ((zb - za) * i) / n);
      rail(xa, za, xb, zb);
    };
    span(x0, z1 - 1.2, x0, z0);
    span(x0, z0, x1, z0);
    span(x1, z0, x1, z1 - 1.2);
    const fenceGeo = mergeGeometries(fence, false);
    fence.forEach((g) => g.dispose());
    if (fenceGeo) {
      const fm = new THREE.Mesh(fenceGeo, mats.solid);
      addWhiteColors(fm);
      fm.castShadow = true;
      fm.receiveShadow = true;
      this.group.add(fm);
    }
    // path border: thin overlay quads just above the grass
    const border = new THREE.Mesh(plotBorderGeometry(this.slot.cx, this.slot.cz, y0 + 0.004), new THREE.MeshLambertMaterial({
      map: getAtlas(),
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -2,
    }));
    border.receiveShadow = true;
    this.borderMat = border.material as THREE.Material;
    this.group.add(border);
  }

  private rebuild(): void {
    if (this.buildMesh) {
      this.group.remove(this.buildMesh);
      disposeGroup(this.buildMesh);
      this.buildMesh = null;
    }
    if (this.placed === 0) return;
    const blocks = new Map<string, number>();
    const key = (x: number, y: number, z: number): string => `${x},${y},${z}`;
    for (let i = 0; i < this.placed; i++) {
      const s = this.pattern[i];
      const [x, z] = this.cell(s.a, s.b);
      blocks.set(key(x, this.baseY + s.y, z), s.id);
    }
    const positions = [...blocks.keys()].map((k) => k.split(',').map(Number) as [number, number, number]);
    const get = (x: number, y: number, z: number): number => blocks.get(key(x, y, z)) ?? this.vox.get(x, y, z);
    this.buildMesh = groupFrom(meshBlocks(positions, get, { skipBottom: true }));
    this.group.add(this.buildMesh);
  }

  /** place the next block; returns the world position, and whether the structure completed & reset */
  placeBlock(): { pos: THREE.Vector3; reset: boolean } {
    if (this.placed >= BUILD_MAX) {
      const pos = this.world(1.5, -1.5, 2.5);
      this.placed = 0;
      this.rebuild();
      return { pos, reset: true };
    }
    const s = this.pattern[this.placed];
    const pos = this.world(s.a, s.b, s.y + 0.5);
    this.placed++;
    this.rebuild();
    // pop-in overlay
    if (this.pop) {
      this.group.remove(this.pop.mesh);
      this.pop.mesh.geometry.dispose();
    }
    const def = s.id;
    const m = new THREE.Mesh(tiledBox(1.02, 1.02, 1.02, popTile(def)), new THREE.MeshBasicMaterial({ map: getAtlas(), transparent: true, opacity: 0.9 }));
    m.position.copy(pos);
    m.scale.setScalar(0.2);
    this.pop = { mesh: m, t: 0 };
    this.group.add(m);
    if (this.placed >= BUILD_MAX) return { pos, reset: false };
    return { pos, reset: false };
  }

  get full(): boolean {
    return this.placed >= BUILD_MAX;
  }

  update(dt: number): void {
    if (this.pop) {
      this.pop.t += dt;
      const k = Math.min(1, this.pop.t / 0.28);
      const s = k < 1 ? 0.2 + (1.15 - 0.2) * easeOutBack(k) : 1;
      this.pop.mesh.scale.setScalar(s);
      (this.pop.mesh.material as THREE.MeshBasicMaterial).opacity = 0.9 * (1 - k);
      if (k >= 1) {
        this.group.remove(this.pop.mesh);
        this.pop.mesh.geometry.dispose();
        (this.pop.mesh.material as THREE.Material).dispose();
        this.pop = null;
      }
    }
  }

  dispose(): void {
    for (let a = -PLOT_HALF; a <= PLOT_HALF; a++)
      for (let b = -PLOT_HALF; b <= PLOT_HALF; b++) {
        const [x, z] = this.cell(a, b);
        this.vox.blocked.delete(this.vox.col(x, z));
      }
    disposeGroup(this.group);
    this.borderMat?.dispose();
    this.group.removeFromParent();
  }
}

/** a 1-block ring of path texture around the 7×7 plot */
function plotBorderGeometry(cx: number, cz: number, y: number): THREE.BufferGeometry {
  const pos: number[] = [];
  const uv: number[] = [];
  const nor: number[] = [];
  const idx: number[] = [];
  for (let a = -PLOT_HALF; a <= PLOT_HALF; a++)
    for (let b = -PLOT_HALF; b <= PLOT_HALF; b++) {
      if (Math.abs(a) !== PLOT_HALF && Math.abs(b) !== PLOT_HALF) continue;
      if (b === PLOT_HALF && Math.abs(a) <= 1) continue; // entrance
      const x = cx + a;
      const z = cz + b;
      const t = hash3(x, 7, z, 17) < 0.7 ? T.PathTop : T.Gravel;
      const [u0, v0, u1, v1] = tileUV(t);
      const base = pos.length / 3;
      pos.push(x, y, z + 1, x + 1, y, z + 1, x + 1, y, z, x, y, z);
      uv.push(u0, v1, u1, v1, u1, v0, u0, v0);
      nor.push(0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0);
      idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setIndex(idx);
  return g;
}

function popTile(id: number): number {
  const tiles: Record<number, number> = {
    [B.OakPlanks]: T.OakPlanks,
    [B.Cobble]: T.Cobble,
    [B.OakLog]: T.OakLog,
    [B.DarkPlanks]: T.DarkPlanks,
    [B.SmoothStone]: T.SmoothStone,
    [B.StoneBricks]: T.StoneBricks,
    [B.Bricks]: T.Bricks,
    [B.WhiteWool]: T.WhiteWool,
    [B.RedWool]: T.RedWool,
    [B.DarkLog]: T.DarkLog,
    [B.MossyCobble]: T.MossyCobble,
    [B.Quartz]: T.Quartz,
    [B.GoldTrim]: T.GoldTrim,
    [B.PurpleWool]: T.PurpleWool,
    [B.Hay]: T.HaySide,
    [B.Glass]: T.WhiteWool,
  };
  return tiles[id] ?? T.OakPlanks;
}

function easeOutBack(x: number): number {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
}

function groupFrom(data: { solid: THREE.BufferGeometry | null; cutout: THREE.BufferGeometry | null; glow: THREE.BufferGeometry | null }): THREE.Group {
  const g = new THREE.Group();
  const mats = worldMaterials();
  if (data.solid) {
    const m = new THREE.Mesh(data.solid, mats.solid);
    m.castShadow = m.receiveShadow = true;
    g.add(m);
  }
  if (data.cutout) {
    const m = new THREE.Mesh(data.cutout, mats.cutout);
    m.castShadow = m.receiveShadow = true;
    g.add(m);
  }
  if (data.glow) g.add(new THREE.Mesh(data.glow, mats.glow));
  return g;
}

/** dispose geometries (shared world materials are kept) */
export function disposeGroup(g: THREE.Object3D): void {
  g.traverse((o) => {
    const m = o as THREE.Mesh;
    if (m.isMesh) m.geometry.dispose();
  });
}

