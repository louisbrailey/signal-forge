// Voxel island: deterministic generation, decoration, meshing and walkability / pathfinding.
import * as THREE from 'three';
import { B, BLOCKS, isSolid } from './blocks';
import { meshBlocks } from './mesher';
import { Simplex2, hash3, smoothstep, lerp, clamp } from './noise';
import {
  HALF, HEIGHT, SEA, WORLD, VILLAGE_Y, HALL_Y, HALL, PLAZA, PLOTS, PLOT_HALF, PLOT_ROWS, AVENUE,
} from './layout';
import { getAtlas } from './textures';

export const SEED = 1337;

const tintNoise = new Simplex2(SEED + 99);
const TINT_A = [1.04, 1.02, 0.8] as const; // warm / dry
const TINT_B = [0.88, 1.0, 0.98] as const; // lush / cool
const _tint: [number, number, number] = [1, 1, 1];
function biomeTint(x: number, _y: number, z: number, id: number, face: number): readonly [number, number, number] | null {
  const grassy = (id === B.Grass && face === 2) || id === B.TallGrass || id === B.Fern || id === B.OakLeaves;
  if (!grassy) return null;
  const t = tintNoise.fbm(x / 28, z / 28, 2) * 0.5 + 0.5 + (id === B.OakLeaves ? -0.15 : 0);
  const k = Math.max(0, Math.min(1, t));
  _tint[0] = TINT_A[0] + (TINT_B[0] - TINT_A[0]) * k;
  _tint[1] = TINT_A[1] + (TINT_B[1] - TINT_A[1]) * k;
  _tint[2] = TINT_A[2] + (TINT_B[2] - TINT_A[2]) * k;
  return _tint;
}

export class VoxelWorld {
  readonly blocks = new Uint8Array(WORLD * HEIGHT * WORLD);
  /** surface (top natural block) height per column */
  readonly surface = new Int16Array(WORLD * WORLD);
  /** 1 = reserved (paths, plots, plaza, hall): no vegetation */
  readonly reserved = new Uint8Array(WORLD * WORLD);
  /** standable y (feet) per column, or -1 */
  readonly walkY = new Int16Array(WORLD * WORLD);
  /** columns temporarily blocked by dynamic props (plot workshops) */
  readonly blocked = new Set<number>();

  inside(x: number, y: number, z: number): boolean {
    return x >= -HALF && x < HALF && z >= -HALF && z < HALF && y >= 0 && y < HEIGHT;
  }
  private idx(x: number, y: number, z: number): number {
    return ((x + HALF) * WORLD + (z + HALF)) * HEIGHT + y;
  }
  col(x: number, z: number): number {
    return (x + HALF) * WORLD + (z + HALF);
  }
  get(x: number, y: number, z: number): number {
    if (!this.inside(x, y, z)) return y < SEA - 4 ? B.Stone : 0;
    return this.blocks[this.idx(x, y, z)];
  }
  set(x: number, y: number, z: number, id: number): void {
    if (!this.inside(x, y, z)) return;
    this.blocks[this.idx(x, y, z)] = id;
  }
  surf(x: number, z: number): number {
    if (x < -HALF || x >= HALF || z < -HALF || z >= HALF) return SEA - 5;
    return this.surface[this.col(x, z)];
  }
  reserve(x: number, z: number): void {
    if (x < -HALF || x >= HALF || z < -HALF || z >= HALF) return;
    this.reserved[this.col(x, z)] = 1;
  }
  /** no trees/rocks, but flowers may grow (unused plots) */
  reserveSoft(x: number, z: number): void {
    if (x < -HALF || x >= HALF || z < -HALF || z >= HALF) return;
    const c = this.col(x, z);
    if (this.reserved[c] === 0) this.reserved[c] = 2;
  }
  isReserved(x: number, z: number): boolean {
    if (x < -HALF || x >= HALF || z < -HALF || z >= HALF) return true;
    return this.reserved[this.col(x, z)] === 1;
  }
  /** set the surface block of a column (keeps height) */
  setTop(x: number, z: number, id: number): void {
    this.set(x, this.surf(x, z), z, id);
  }

  // ---------------------------------------------------------------- generation
  generate(): void {
    const n = new Simplex2(SEED);
    const n2 = new Simplex2(SEED + 1);
    for (let x = -HALF; x < HALF; x++)
      for (let z = -HALF; z < HALF; z++) {
        const ang = Math.atan2(z, x);
        const rad = 41 + n.noise(Math.cos(ang) * 1.3 + 5, Math.sin(ang) * 1.3) * 4 + (z > 0 ? 3 : 0);
        const d = Math.hypot(x, z * (z > 0 ? 0.9 : 1)) / rad;
        let h = SEA + 3 + n.fbm(x / 36, z / 36, 4) * 4 + Math.max(0, n2.fbm(x / 22 + 9, z / 22, 3)) * 6;
        // northern highlands behind the hall
        const north = smoothstep(-20, -40, z) * (1 - smoothstep(0.75, 1.0, d));
        h += north * (5 + Math.max(0, n2.noise(x / 12, z / 12)) * 9);
        // coastline falloff
        h = lerp(h, SEA - 5, smoothstep(0.78, 1.08, d));
        // village flatten
        // village flatten: union of a disc around the plaza and the rounded street grid
        const dv = villageDist(x, z);
        h = lerp(VILLAGE_Y + (n.noise(x / 9, z / 9) > 0.55 ? 1 : 0), h, smoothstep(0, 5, dv));
        if (dv <= 0) h = VILLAGE_Y;
        // hall hill
        const dh = Math.hypot(x - HALL.x, z - HALL.z);
        const hillR = HALL.plateau + n.noise(ang * 2, 3) * 1.5;
        const hillT = smoothstep(hillR, hillR + 9, dh);
        h = Math.max(hillT < 1 ? lerp(HALL_Y, VILLAGE_Y, hillT) : -99, h);
        if (dh <= HALL.plateau) h = HALL_Y;
        // ramp from plaza to hall
        if (Math.abs(x) <= 2 && z <= PLAZA.z - PLAZA.r + 1 && z >= HALL.z + HALL.plateau - 1) {
          const t = clamp((PLAZA.z - PLAZA.r - z) / (PLAZA.z - PLAZA.r - (HALL.z + HALL.plateau)), 0, 1);
          h = Math.round(lerp(VILLAGE_Y, HALL_Y, t));
        }
        const hi = clamp(Math.round(h), 1, HEIGHT - 12);
        this.surface[this.col(x, z)] = hi;
        for (let y = 0; y <= hi; y++) {
          let id: number = B.Stone;
          if (y >= hi - 3) id = B.Dirt;
          if (y === hi) {
            if (hi <= SEA + 1) id = n2.noise(x / 6, z / 6) > 0.45 && hi < SEA - 1 ? B.Gravel : B.Sand;
            else if (hi > 25 && n.noise(x / 5, z / 5) > -0.1) id = B.Stone;
            else id = B.Grass;
          } else if (hi <= SEA + 1 && y >= hi - 2) id = B.Sand;
          this.set(x, y, z, id);
        }
      }
  }

  /** paths, plaza and plot reservation (before structures & vegetation) */
  layVillage(): void {
    // plaza: cobble disc with a stone-brick rim and a gold compass rose
    for (let x = -PLAZA.r - 1; x <= PLAZA.r + 1; x++)
      for (let z = -PLAZA.r - 1; z <= PLAZA.r + 1; z++) {
        const d = Math.hypot(x, z);
        if (d > PLAZA.r + 0.6) continue;
        const wx = PLAZA.x + x;
        const wz = PLAZA.z + z;
        let id: number = B.Cobble;
        if (d > PLAZA.r - 0.4) id = B.StoneBricks;
        else if (d < 1.2) id = B.SmoothStone;
        else if ((x === 0 || z === 0) && d < 3.5) id = B.StoneBricks;
        else if (hash3(wx, 0, wz, 3) < 0.2) id = B.MossyCobble;
        this.setTop(wx, wz, id);
        this.reserve(wx, wz);
      }
    // east-west streets in front of each plot row, and the central avenue
    for (const row of PLOT_ROWS) {
      const ext = Math.max(...row.xs) + PLOT_HALF + 1;
      for (let x = -ext; x <= ext; x++) for (let z = row.street; z <= row.street + 1; z++) this.pathAt(x, z);
    }
    for (let z = AVENUE.z0; z <= AVENUE.z1 + 1; z++) for (let x = AVENUE.x0; x <= AVENUE.x1; x++) this.pathAt(x, z);
    // a little spur from every plot entrance to its street
    for (const p of PLOTS) for (let x = p.cx - 1; x <= p.cx + 1; x++) this.pathAt(x, p.cz + PLOT_HALF + 1, true);
    for (let z = HALL.z + HALL.plateau - 1; z <= PLAZA.z - PLAZA.r; z++)
      for (let x = -2; x <= 2; x++) {
        const edge = Math.abs(x) === 2;
        const y = this.surf(x, z);
        this.set(x, y, z, edge ? B.StoneBricks : B.Path);
        this.reserve(x, z);
        if (edge) this.reserve(x + Math.sign(x), z);
      }
    // plots: keep grass, but reserve so no plants spawn there
    for (const p of PLOTS)
      for (let a = -PLOT_HALF; a <= PLOT_HALF; a++)
        for (let b = -PLOT_HALF; b <= PLOT_HALF; b++) {
          const x = p.cx + a;
          const z = p.cz + b;
          if (this.get(x, this.surf(x, z), z) === B.Grass) this.reserveSoft(x, z);
        }
  }

  private pathAt(x: number, z: number, force = false): void {
    if (x < -HALF || x >= HALF || z < -HALF || z >= HALF) return;
    const top = this.get(x, this.surf(x, z), z);
    if (top !== B.Grass && top !== B.Dirt) return;
    // skip plot interiors
    if (!force) for (const p of PLOTS) if (Math.abs(x - p.cx) <= PLOT_HALF && Math.abs(z - p.cz) <= PLOT_HALF) return;
    const r = hash3(x, 1, z, 9);
    this.setTop(x, z, r < 0.62 ? B.Path : r < 0.9 ? B.Gravel : B.CoarseDirt);
    this.reserve(x, z);
  }

  /** trees, flowers, grass and rocks (after structures) */
  decorate(): void {
    const n = new Simplex2(SEED + 7);
    // two small wheat farms in the fields south-west / south-east of the plot grid
    for (const sx of [-1, 1]) {
      for (let dx = 0; dx < 8; dx++)
        for (let z = 26; z <= 31; z++) {
          const x = sx < 0 ? -27 + dx : 20 + dx;
          const y = this.surf(x, z);
          if (y !== VILLAGE_Y || this.get(x, y, z) !== B.Grass || this.reserved[this.col(x, z)] === 1) continue;
          const edge = dx === 0 || dx === 7 || z === 26 || z === 31;
          if (edge) {
            this.setTop(x, z, B.OakLog);
          } else {
            this.setTop(x, z, B.Farmland);
            this.set(x, y + 1, z, B.Wheat);
          }
          this.reserve(x, z);
        }
      const hx = sx < 0 ? -29 : 29;
      if (this.get(hx, VILLAGE_Y + 1, 27) === 0) {
        this.set(hx, VILLAGE_Y + 1, 27, B.Hay);
        this.set(hx, VILLAGE_Y + 1, 28, B.Hay);
        this.set(hx, VILLAGE_Y + 2, 27, B.Hay);
        this.reserve(hx, 27);
        this.reserve(hx, 28);
      }
    }
    // trees on a jittered grid
    const cell = 5;
    for (let gx = -HALF; gx < HALF; gx += cell)
      for (let gz = -HALF; gz < HALF; gz += cell) {
        const x = gx + Math.floor(hash3(gx, 0, gz, 21) * cell);
        const z = gz + Math.floor(hash3(gx, 1, gz, 21) * cell);
        if (x < -HALF + 2 || x >= HALF - 2 || z < -HALF + 2 || z >= HALF - 2) continue;
        const y = this.surf(x, z);
        if (this.get(x, y, z) !== B.Grass || y <= SEA + 1) continue;
        const dv = Math.hypot(x - PLAZA.x, z - PLAZA.z);
        const dh = Math.hypot(x - HALL.x, z - HALL.z);
        let near = false;
        for (let dx = -2; dx <= 2 && !near; dx++) for (let dz = -2; dz <= 2; dz++) if (this.isReserved(x + dx, z + dz)) near = true;
        if (near || dh < HALL.plateau + 2 || Math.abs(x) < 4) continue;
        const forest = n.noise(x / 18, z / 18);
        const p = dv < 33 ? 0.22 : 0.45 + forest * 0.35;
        if (hash3(x, 2, z, 22) > p) continue;
        this.tree(x, y + 1, z, hash3(x, 3, z, 23) < 0.18 ? B.BlossomLeaves : B.OakLeaves);
      }
    // rocks
    for (let i = 0; i < 26; i++) {
      const x = Math.floor(hash3(i, 5, 0, 31) * (WORLD - 10)) - HALF + 5;
      const z = Math.floor(hash3(i, 6, 0, 31) * (WORLD - 10)) - HALF + 5;
      const y = this.surf(x, z);
      if (this.isReserved(x, z) || y <= SEA) continue;
      const top = this.get(x, y, z);
      if (top !== B.Grass && top !== B.Sand && top !== B.Stone) continue;
      const big = hash3(i, 7, 0, 31) < 0.4;
      for (let dx = -1; dx <= 1; dx++)
        for (let dz = -1; dz <= 1; dz++) {
          if (!big && (dx !== 0 && dz !== 0)) continue;
          if (hash3(x + dx, 9, z + dz, 32) < 0.35 && (dx || dz)) continue;
          const yy = this.surf(x + dx, z + dz) + 1;
          if (this.isReserved(x + dx, z + dz) || this.get(x + dx, yy, z + dz) !== 0) continue;
          this.set(x + dx, yy, z + dz, hash3(x + dx, 8, z + dz, 33) < 0.4 ? B.MossyCobble : B.Stone);
          if (big && dx === 0 && dz === 0) this.set(x, yy + 1, z, B.Cobble);
        }
    }
    // ground cover
    for (let x = -HALF; x < HALF; x++)
      for (let z = -HALF; z < HALF; z++) {
        const y = this.surf(x, z);
        if (this.get(x, y, z) !== B.Grass || this.reserved[this.col(x, z)] === 1 || this.get(x, y + 1, z) !== 0) continue;
        const r = hash3(x, y, z, 41);
        const meadow = n.noise(x / 10 + 30, z / 10) * 0.5 + 0.5;
        if (r < 0.1 + meadow * 0.12) this.set(x, y + 1, z, B.TallGrass);
        else if (r < 0.13 + meadow * 0.16) {
          const f = hash3(x, y, z, 42);
          const patch = n.noise(x / 7, z / 7);
          const id = patch > 0.3 ? (f < 0.6 ? B.FlowerYellow : B.FlowerRed) : patch < -0.3 ? (f < 0.5 ? B.FlowerBlue : B.FlowerPink) : f < 0.5 ? B.FlowerRed : B.Fern;
          this.set(x, y + 1, z, id);
        } else if (r > 0.995) this.set(x, y + 1, z, B.Mushroom);
      }
  }

  tree(x: number, y: number, z: number, leaves: number): void {
    const hgt = 4 + Math.floor(hash3(x, y, z, 51) * 3);
    for (let i = 0; i < hgt; i++) this.set(x, y + i, z, B.OakLog);
    const top = y + hgt;
    for (let dy = -2; dy <= 1; dy++) {
      const r = dy <= -1 ? 2 : dy === 0 ? 1.6 : 1;
      for (let dx = -2; dx <= 2; dx++)
        for (let dz = -2; dz <= 2; dz++) {
          const d = Math.hypot(dx, dz);
          if (d > r + 0.5) continue;
          if (d > r - 0.2 && hash3(x + dx, top + dy, z + dz, 52) < 0.4) continue;
          if (this.get(x + dx, top + dy, z + dz) === 0) this.set(x + dx, top + dy, z + dz, leaves);
        }
    }
    this.set(x, top, z, leaves);
    this.set(x, this.surf(x, z), z, B.Dirt);
  }

  // ---------------------------------------------------------------- walkability & paths
  computeWalk(): void {
    for (let x = -HALF; x < HALF; x++)
      for (let z = -HALF; z < HALF; z++) {
        let wy = -1;
        for (let y = SEA + 1; y < HEIGHT - 2; y++) {
          if (isSolid(this.get(x, y - 1, z)) && !isSolid(this.get(x, y, z)) && !isSolid(this.get(x, y + 1, z))) {
            wy = y;
            break;
          }
        }
        this.walkY[this.col(x, z)] = wy;
      }
  }

  /** feet height at a continuous position (smooth-ish), falls back to surface */
  heightAt(x: number, z: number): number {
    const bx = Math.floor(x);
    const bz = Math.floor(z);
    if (bx < -HALF || bx >= HALF || bz < -HALF || bz >= HALF) return SEA + 1;
    const w = this.walkY[this.col(bx, bz)];
    return w >= 0 ? w : this.surf(bx, bz) + 1;
  }

  walkable(x: number, z: number): boolean {
    if (x < -HALF || x >= HALF || z < -HALF || z >= HALF) return false;
    const c = this.col(x, z);
    return this.walkY[c] >= 0 && !this.blocked.has(c);
  }

  /** A* on the column grid. Returns block-centre waypoints (x+0.5, z+0.5), excluding the start. */
  findPath(sx: number, sz: number, tx: number, tz: number, maxNodes = 6000): [number, number][] | null {
    const x0 = Math.floor(sx);
    const z0 = Math.floor(sz);
    const x1 = Math.floor(tx);
    const z1 = Math.floor(tz);
    if (x0 === x1 && z0 === z1) return [[tx, tz]];
    const N = WORLD * WORLD;
    const g = new Float32Array(N).fill(Infinity);
    const came = new Int32Array(N).fill(-1);
    const closed = new Uint8Array(N);
    const start = this.col(clamp(x0, -HALF, HALF - 1), clamp(z0, -HALF, HALF - 1));
    const goal = this.col(clamp(x1, -HALF, HALF - 1), clamp(z1, -HALF, HALF - 1));
    const heap: number[] = [];
    const f = new Float32Array(N);
    const push = (i: number): void => {
      heap.push(i);
      let k = heap.length - 1;
      while (k > 0) {
        const p = (k - 1) >> 1;
        if (f[heap[p]] <= f[heap[k]]) break;
        [heap[p], heap[k]] = [heap[k], heap[p]];
        k = p;
      }
    };
    const pop = (): number => {
      const top = heap[0];
      const last = heap.pop()!;
      if (heap.length) {
        heap[0] = last;
        let k = 0;
        for (;;) {
          const l = k * 2 + 1;
          const r = l + 1;
          let m = k;
          if (l < heap.length && f[heap[l]] < f[heap[m]]) m = l;
          if (r < heap.length && f[heap[r]] < f[heap[m]]) m = r;
          if (m === k) break;
          [heap[m], heap[k]] = [heap[k], heap[m]];
          k = m;
        }
      }
      return top;
    };
    const gx = (i: number): number => Math.floor(i / WORLD) - HALF;
    const gz = (i: number): number => (i % WORLD) - HALF;
    const hcost = (i: number): number => Math.hypot(gx(i) - x1, gz(i) - z1) * 0.8;
    g[start] = 0;
    f[start] = hcost(start);
    push(start);
    let visited = 0;
    let found = false;
    while (heap.length && visited < maxNodes) {
      const cur = pop();
      if (closed[cur]) continue;
      closed[cur] = 1;
      visited++;
      if (cur === goal) {
        found = true;
        break;
      }
      const cx = gx(cur);
      const cz = gz(cur);
      const cy = this.walkY[cur] >= 0 ? this.walkY[cur] : this.surf(cx, cz) + 1;
      for (let dx = -1; dx <= 1; dx++)
        for (let dz = -1; dz <= 1; dz++) {
          if (!dx && !dz) continue;
          const nx = cx + dx;
          const nz = cz + dz;
          if (!this.walkable(nx, nz) && !(nx === x1 && nz === z1)) continue;
          if (nx < -HALF || nx >= HALF || nz < -HALF || nz >= HALF) continue;
          const ni = this.col(nx, nz);
          if (closed[ni]) continue;
          const ny = this.walkY[ni] >= 0 ? this.walkY[ni] : cy;
          if (Math.abs(ny - cy) > 1) continue;
          if (dx && dz) {
            // no corner cutting
            if (!this.walkable(cx + dx, cz) || !this.walkable(cx, cz + dz)) continue;
            const a = this.walkY[this.col(cx + dx, cz)];
            const b = this.walkY[this.col(cx, cz + dz)];
            if (a !== cy || b !== cy || ny !== cy) continue;
          }
          const top = this.get(nx, ny - 1, nz);
          const pathy = top === B.Path || top === B.Gravel || top === B.Cobble || top === B.StoneBricks || top === B.SmoothStone || top === B.CoarseDirt;
          const step = (dx && dz ? 1.414 : 1) * (pathy ? 0.75 : 1.15) + (ny !== cy ? 0.3 : 0);
          const ng = g[cur] + step;
          if (ng < g[ni]) {
            g[ni] = ng;
            came[ni] = cur;
            f[ni] = ng + hcost(ni);
            push(ni);
          }
        }
    }
    if (!found) return null;
    const out: [number, number][] = [];
    let c = goal;
    while (c !== start && c >= 0) {
      out.push([gx(c) + 0.5, gz(c) + 0.5]);
      c = came[c];
    }
    out.reverse();
    // replace last waypoint with the exact target
    if (out.length) out[out.length - 1] = [tx, tz];
    return simplify(out);
  }

  // ---------------------------------------------------------------- meshing
  buildMeshes(): THREE.Group {
    const positions: [number, number, number][] = [];
    for (let x = -HALF; x < HALF; x++)
      for (let z = -HALF; z < HALF; z++)
        for (let y = 0; y < HEIGHT; y++) if (this.blocks[this.idx(x, y, z)] !== 0) positions.push([x, y, z]);
    const data = meshBlocks(positions, (x, y, z) => this.get(x, y, z), {
      skipBottom: true,
      plants: 'skip',
      tint: biomeTint,
      outside: (x, _y, z) => x < -HALF || x >= HALF || z < -HALF || z >= HALF,
    });
    const group = new THREE.Group();
    group.name = 'terrain';
    const mats = worldMaterials();
    if (data.solid) {
      const m = new THREE.Mesh(data.solid, mats.solid);
      m.castShadow = true;
      m.receiveShadow = true;
      group.add(m);
    }
    if (data.cutout) {
      const m = new THREE.Mesh(data.cutout, mats.cutout);
      m.castShadow = true;
      m.receiveShadow = true;
      group.add(m);
    }
    if (data.glow) group.add(new THREE.Mesh(data.glow, mats.glow));
    group.add(this.buildPlantMesh());
    return group;
  }

  /** plants live in their own mesh so clearing a plot only rebuilds this (fast) */
  buildPlantMesh(): THREE.Object3D {
    const positions: [number, number, number][] = [];
    for (let x = -HALF; x < HALF; x++)
      for (let z = -HALF; z < HALF; z++) {
        const s = this.surf(x, z);
        for (let y = s + 1; y <= s + 3 && y < HEIGHT; y++) {
          const id = this.blocks[this.idx(x, y, z)];
          if (id !== 0 && BLOCKS[id].kind === 'plant') positions.push([x, y, z]);
        }
      }
    const data = meshBlocks(positions, (x, y, z) => this.get(x, y, z), { plants: 'only', tint: biomeTint });
    const obj = data.cutout ? new THREE.Mesh(data.cutout, worldMaterials().cutout) : new THREE.Object3D();
    obj.name = 'plants';
    (obj as THREE.Mesh).receiveShadow = true;
    return obj;
  }

  /** remove plants in a rectangle; returns true if anything changed */
  clearPlants(x0: number, z0: number, x1: number, z1: number): boolean {
    let changed = false;
    for (let x = x0; x <= x1; x++)
      for (let z = z0; z <= z1; z++) {
        if (x < -HALF || x >= HALF || z < -HALF || z >= HALF) continue;
        const s = this.surf(x, z);
        for (let y = s + 1; y <= s + 2; y++) {
          const id = this.get(x, y, z);
          if (id !== 0 && BLOCKS[id].kind === 'plant') {
            this.set(x, y, z, 0);
            changed = true;
          }
        }
      }
    return changed;
  }
}

/** signed-ish distance (blocks) outside the flat village zone; <= 0 inside */
function villageDist(x: number, z: number): number {
  const disc = Math.hypot(x - PLAZA.x, z - PLAZA.z) - 20;
  // rounded rectangle covering the plot grid
  const hx = 37.5;
  const z0 = -5.5;
  const z1 = 33.5;
  const dx = Math.abs(x) - hx;
  const dz = Math.max(z0 - z, z - z1);
  const ox = Math.max(dx, 0);
  const oz = Math.max(dz, 0);
  const rect = Math.hypot(ox, oz) + Math.min(Math.max(dx, dz), 0);
  // trim the southern corners where the island narrows
  const corner = Math.hypot(Math.max(0, Math.abs(x) - 18), Math.max(0, z - 22)) - 12;
  return Math.min(disc, Math.max(rect, corner));
}

/** drop collinear waypoints */
function simplify(pts: [number, number][]): [number, number][] {
  if (pts.length < 3) return pts;
  const out: [number, number][] = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = out[out.length - 1];
    const b = pts[i];
    const c = pts[i + 1];
    const d1x = Math.sign(Math.round((b[0] - a[0]) * 2));
    const d1z = Math.sign(Math.round((b[1] - a[1]) * 2));
    const d2x = Math.sign(Math.round((c[0] - b[0]) * 2));
    const d2z = Math.sign(Math.round((c[1] - b[1]) * 2));
    if (d1x !== d2x || d1z !== d2z) out.push(b);
  }
  out.push(pts[pts.length - 1]);
  return out;
}

export interface WorldMaterials {
  solid: THREE.MeshLambertMaterial;
  cutout: THREE.MeshLambertMaterial;
  glow: THREE.MeshBasicMaterial;
}

let mats: WorldMaterials | null = null;
export function worldMaterials(): WorldMaterials {
  if (mats) return mats;
  const atlas = getAtlas();
  mats = {
    solid: new THREE.MeshLambertMaterial({ map: atlas, vertexColors: true }),
    cutout: new THREE.MeshLambertMaterial({ map: atlas, vertexColors: true, alphaTest: 0.5 }),
    glow: new THREE.MeshBasicMaterial({ map: atlas, color: new THREE.Color(1.4, 1.3, 1.1) }),
  };
  return mats;
}

export function disposeWorldMaterials(): void {
  if (!mats) return;
  mats.solid.dispose();
  mats.cutout.dispose();
  mats.glow.dispose();
  mats = null;
}
