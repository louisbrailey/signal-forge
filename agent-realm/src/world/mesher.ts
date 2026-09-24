// Voxel mesher: hidden-face culling, per-vertex ambient occlusion, baked face shading.
// Produces up to three merged geometries: solid (opaque), cutout (leaves/glass/plants, alpha-tested), glow (unlit).
import * as THREE from 'three';
import { B, BLOCKS, isOpaque } from './blocks';
import { tileUV } from './textures';
import { hash3 } from './noise';

type V3 = readonly [number, number, number];

interface FaceDef {
  n: V3;
  u: V3; // right axis as seen from outside
  v: V3; // up axis as seen from outside
  shade: number;
}

// order matches BlockDef.tiles: +x, -x, +y, -y, +z, -z
const FACES: FaceDef[] = [
  { n: [1, 0, 0], u: [0, 0, -1], v: [0, 1, 0], shade: 0.8 },
  { n: [-1, 0, 0], u: [0, 0, 1], v: [0, 1, 0], shade: 0.8 },
  { n: [0, 1, 0], u: [1, 0, 0], v: [0, 0, -1], shade: 1.0 },
  { n: [0, -1, 0], u: [1, 0, 0], v: [0, 0, 1], shade: 0.58 },
  { n: [0, 0, 1], u: [1, 0, 0], v: [0, 1, 0], shade: 0.9 },
  { n: [0, 0, -1], u: [-1, 0, 0], v: [0, 1, 0], shade: 0.9 },
];

const FRONT_FACE = [4, 0, 5, 1];
const OPPOSITE = [1, 0, 3, 2, 5, 4];

const AO_CURVE = [0.5, 0.68, 0.84, 1.0];

class Buf {
  pos: number[] = [];
  nor: number[] = [];
  uv: number[] = [];
  col: number[] = [];
  idx: number[] = [];
  get count(): number {
    return this.pos.length / 3;
  }
  toGeometry(): THREE.BufferGeometry | null {
    if (this.pos.length === 0) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(this.nor, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(this.uv, 2));
    g.setAttribute('color', new THREE.Float32BufferAttribute(this.col, 3));
    g.setIndex(this.count > 65535 ? new THREE.Uint32BufferAttribute(this.idx, 1) : new THREE.Uint16BufferAttribute(this.idx, 1));
    g.computeBoundingSphere();
    g.computeBoundingBox();
    return g;
  }
}

export interface MeshData {
  solid: THREE.BufferGeometry | null;
  cutout: THREE.BufferGeometry | null;
  glow: THREE.BufferGeometry | null;
}

export type Getter = (x: number, y: number, z: number) => number;

/**
 * Mesh the blocks at the given positions. `get` answers for any coordinate (including neighbours
 * outside the set) and is used for culling + AO. Coordinates are integer block corners.
 */
export function meshBlocks(
  positions: Iterable<readonly [number, number, number]>,
  get: Getter,
  opts: {
    skipBottom?: boolean;
    outside?: (x: number, y: number, z: number) => boolean;
    /** per-block colour tint (multiplied into vertex colours), e.g. biome grass variation */
    tint?: (x: number, y: number, z: number, id: number, face: number) => readonly [number, number, number] | null;
    /** plants (cross sprites): include (default), skip, or only */
    plants?: 'include' | 'skip' | 'only';
    /** rotate 'front' tiles: 0:+z 1:+x 2:-z 3:-x */
    facing?: (x: number, y: number, z: number) => number | undefined;
  } = {},
): MeshData {
  const solid = new Buf();
  const cutout = new Buf();
  const glow = new Buf();
  const occ = (x: number, y: number, z: number): number => (isOpaque(get(x, y, z)) ? 1 : 0);

  for (const [x, y, z] of positions) {
    const id = get(x, y, z);
    if (id === 0) continue;
    const def = BLOCKS[id];
    if (!def) continue;
    if (def.kind === 'plant') {
      if (opts.plants !== 'skip') emitCross(cutout, x, y, z, def.tiles[0], opts.tint ? opts.tint(x, y, z, id, 2) : null);
      continue;
    }
    if (opts.plants === 'only') continue;
    const buf = def.kind === 'glow' ? glow : def.kind === 'cutout' ? cutout : solid;
    const dir = opts.facing ? opts.facing(x, y, z) : undefined;
    for (let f = 0; f < 6; f++) {
      const F = FACES[f];
      if (opts.skipBottom && f === 3) continue;
      const nx = x + F.n[0];
      const ny = y + F.n[1];
      const nz = z + F.n[2];
      if (opts.outside && opts.outside(nx, ny, nz)) continue;
      const nb = get(nx, ny, nz);
      if (nb !== 0) {
        if (isOpaque(nb)) continue;
        if (nb === id && def.kind === 'cutout' && id !== B.OakLeaves && id !== B.BlossomLeaves) continue; // glass-glass
      }
      let tile = def.tiles[f];
      if (dir !== undefined && f !== 2 && f !== 3) {
        const front = FRONT_FACE[dir];
        tile = f === front ? def.tiles[4] : f === OPPOSITE[front] ? def.tiles[5] : def.tiles[0];
      }
      emitFace(buf, x, y, z, F, tile, def.kind === 'glow' ? null : occ, opts.tint ? opts.tint(x, y, z, id, f) : null);
    }
  }
  return { solid: solid.toGeometry(), cutout: cutout.toGeometry(), glow: glow.toGeometry() };
}

function emitFace(
  b: Buf,
  x: number,
  y: number,
  z: number,
  F: FaceDef,
  tile: number,
  occ: ((x: number, y: number, z: number) => number) | null,
  tint: readonly [number, number, number] | null = null,
): void {
  const [u0, v0, u1, v1] = tileUV(tile);
  const cx = x + 0.5 + F.n[0] * 0.5;
  const cy = y + 0.5 + F.n[1] * 0.5;
  const cz = z + 0.5 + F.n[2] * 0.5;
  // corners: BL, BR, TR, TL
  const su = [-1, 1, 1, -1];
  const sv = [-1, -1, 1, 1];
  const uvs = [u0, v1, u1, v1, u1, v0, u0, v0];
  const ao = [3, 3, 3, 3];
  const base = b.count;
  const jitter = 0.97 + hash3(x, y, z, 11) * 0.06; // subtle per-block tint variation
  for (let i = 0; i < 4; i++) {
    const px = cx + (F.u[0] * su[i] + F.v[0] * sv[i]) * 0.5;
    const py = cy + (F.u[1] * su[i] + F.v[1] * sv[i]) * 0.5;
    const pz = cz + (F.u[2] * su[i] + F.v[2] * sv[i]) * 0.5;
    b.pos.push(px, py, pz);
    b.nor.push(F.n[0], F.n[1], F.n[2]);
    b.uv.push(uvs[i * 2], uvs[i * 2 + 1]);
    if (occ) {
      const ox = x + F.n[0];
      const oy = y + F.n[1];
      const oz = z + F.n[2];
      const s1 = occ(ox + F.u[0] * su[i], oy + F.u[1] * su[i], oz + F.u[2] * su[i]);
      const s2 = occ(ox + F.v[0] * sv[i], oy + F.v[1] * sv[i], oz + F.v[2] * sv[i]);
      const c = occ(
        ox + F.u[0] * su[i] + F.v[0] * sv[i],
        oy + F.u[1] * su[i] + F.v[1] * sv[i],
        oz + F.u[2] * su[i] + F.v[2] * sv[i],
      );
      ao[i] = s1 && s2 ? 0 : 3 - (s1 + s2 + c);
    }
    const l = occ ? AO_CURVE[ao[i]] * F.shade * jitter : 1;
    if (tint) b.col.push(l * tint[0], l * tint[1], l * tint[2]);
    else b.col.push(l, l, l);
  }
  // flip the quad diagonal to avoid AO interpolation artefacts
  if (ao[0] + ao[2] > ao[1] + ao[3]) b.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  else b.idx.push(base, base + 1, base + 3, base + 1, base + 2, base + 3);
}

function emitCross(b: Buf, x: number, y: number, z: number, tile: number, tint: readonly [number, number, number] | null): void {
  const [u0, v0, u1, v1] = tileUV(tile);
  const r = hash3(x, y, z, 5);
  const ox = x + 0.5 + (r - 0.5) * 0.3;
  const oz = z + 0.5 + (hash3(x, y, z, 6) - 0.5) * 0.3;
  const s = 0.45;
  const h = 0.9 + r * 0.15;
  const shadeK = 0.9 + r * 0.15;
  const quads: [number, number, number, number][] = [
    [-s, -s, s, s],
    [-s, s, s, -s],
  ];
  for (const [ax, az, bx, bz] of quads) {
    const base = b.count;
    b.pos.push(ox + ax, y, oz + az, ox + bx, y, oz + bz, ox + bx, y + h, oz + bz, ox + ax, y + h, oz + az);
    for (let i = 0; i < 4; i++) {
      b.nor.push(0, 1, 0);
      const l = (i < 2 ? 0.8 : 1.05) * shadeK;
      if (tint) b.col.push(l * tint[0], l * tint[1], l * tint[2]);
      else b.col.push(l, l, l);
    }
    b.uv.push(u0, v1, u1, v1, u1, v0, u0, v0);
    // both windings so each side is front-facing with an upward normal (DoubleSide would darken the back)
    b.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    b.idx.push(base, base + 2, base + 1, base, base + 3, base + 2);
  }
}
