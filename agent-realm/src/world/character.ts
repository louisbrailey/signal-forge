// Minecraft-proportioned villagers: box body parts UV-mapped onto a procedural 64×64 skin,
// hats, capes, tools, name tag, speech bubble, selection ring and a small animation state machine.
import * as THREE from 'three';
import type { Agent, AgentStatus, ActivityKind, SkinSpec } from '../../shared/protocol';
import { SKIN_UV, faceRects, skinCanvas, sharedTileTexture, hex, shade, type BoxUV } from './textures';
import { T } from './blocks';
import { NameTag, SpeechBubble, type TagInfo } from './labels';
import type { VoxelWorld } from './terrain';
import type { Effects } from './effects';
import { hashString } from './noise';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const PX = 1 / 16;

function skinBox(w: number, h: number, d: number, b: BoxUV, inflate = 0): THREE.BoxGeometry {
  const g = new THREE.BoxGeometry((w + inflate) * PX, (h + inflate) * PX, (d + inflate) * PX);
  const R = faceRects(b);
  const order = [R.left, R.right, R.top, R.bottom, R.front, R.back]; // +x -x +y -y +z -z
  const uv = g.getAttribute('uv') as THREE.BufferAttribute;
  for (let f = 0; f < 6; f++) {
    const [rx, ry, rw, rh] = order[f];
    for (let i = 0; i < 4; i++) {
      const k = f * 4 + i;
      const u = uv.getX(k);
      const v = uv.getY(k);
      uv.setXY(k, (rx + u * rw) / 64, (ry + (1 - v) * rh) / 64);
    }
  }
  return g;
}

let noiseTex: THREE.Texture | null = null;
function hatNoise(): THREE.Texture {
  if (noiseTex) return noiseTex;
  const c = document.createElement('canvas');
  c.width = c.height = 8;
  const ctx = c.getContext('2d')!;
  for (let y = 0; y < 8; y++)
    for (let x = 0; x < 8; x++) {
      const v = 215 + Math.floor(Math.random() * 40);
      ctx.fillStyle = `rgb(${v},${v},${v})`;
      ctx.fillRect(x, y, 1, 1);
    }
  const t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.NearestFilter;
  t.minFilter = THREE.NearestFilter;
  t.generateMipmaps = false;
  t.colorSpace = THREE.SRGBColorSpace;
  noiseTex = t;
  return t;
}

let ringTex: THREE.Texture | null = null;
function selectionRingTexture(): THREE.Texture {
  if (ringTex) return ringTex;
  const c = document.createElement('canvas');
  c.width = c.height = 32;
  const ctx = c.getContext('2d')!;
  ctx.fillStyle = '#ffd84a';
  ctx.fillRect(2, 2, 28, 2);
  ctx.fillRect(2, 28, 28, 2);
  ctx.fillRect(2, 2, 2, 28);
  ctx.fillRect(28, 2, 2, 28);
  ctx.fillStyle = '#fff6b0';
  for (const [x, y] of [[2, 2], [26, 2], [2, 26], [26, 26]]) ctx.fillRect(x, y, 4, 4);
  ctx.fillStyle = 'rgba(255,216,74,0.25)';
  ctx.fillRect(6, 6, 20, 20);
  const t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.NearestFilter;
  t.minFilter = THREE.NearestFilter;
  t.generateMipmaps = false;
  t.colorSpace = THREE.SRGBColorSpace;
  ringTex = t;
  return t;
}

type Pose = 'walk' | 'idle' | 'working' | 'thinking' | 'waiting' | 'done' | 'error' | 'offline';
type ActionKind = 'hammer' | 'read' | 'catch' | 'cheer' | 'glow' | 'cast' | 'give';

interface Action {
  kind: ActionKind;
  start: number;
  until: number;
}

export interface CharacterCtx {
  vox: VoxelWorld;
  fx: Effects;
  camera: THREE.Camera;
  now: number;
  night: number;
}

const _v = new THREE.Vector3();
const _w = new THREE.Vector3();

function wrapAngle(a: number): number {
  while (a > Math.PI) a -= Math.PI * 2;
  while (a < -Math.PI) a += Math.PI * 2;
  return a;
}

export class Character {
  readonly root = new THREE.Group();
  readonly hitBox: THREE.Mesh;
  agent: Agent;
  private model = new THREE.Group();
  private head = new THREE.Group();
  private body!: THREE.Mesh;
  private armL = new THREE.Group();
  private armR = new THREE.Group();
  private legL = new THREE.Group();
  private legR = new THREE.Group();
  private cape: THREE.Group | null = null;
  private hat: THREE.Group | null = null;
  private hatHeight = 0;
  private tool = new THREE.Group();
  private mat: THREE.MeshLambertMaterial;
  private extraMats: THREE.Material[] = [];
  private skinKey = '';
  private tag: NameTag;
  private bubble = new SpeechBubble();
  private ring: THREE.Mesh;
  private selected = false;
  private hovered = false;

  // movement
  private path: [number, number][] = [];
  private yaw = 0;
  private targetYaw = 0;
  private walking = false;
  private walkPhase = 0;
  private speed = 2.7;
  home = { x: 0, z: 0, yaw: 0 };
  /** what they work on (station / build site / table centre) */
  focus: THREE.Vector3 | null = null;
  secondaryFocus: THREE.Vector3 | null = null;
  private wanderAt = 0;
  private wandering = false;
  private headYaw = 0;
  private headPitch = 0;
  private lookAround = 0;
  private lookAroundAt = 0;
  private lookCamUntil = 0;
  private action: Action | null = null;
  private jumpT = -1;
  private fxTimer = Math.random() * 2;
  private opacity = 1;
  private spawnT = 0;
  private removing = false;
  private removeT = 0;
  private glow = 0;
  private seed: number;
  private y: number;
  removed = false;

  constructor(agent: Agent, x: number, z: number, vox: VoxelWorld) {
    this.agent = agent;
    this.seed = hashString(agent.id);
    this.mat = new THREE.MeshLambertMaterial({ transparent: false, alphaTest: 0.5 });
    this.root.add(this.model);
    this.buildRig();
    this.applySkin(agent.skin);
    this.tag = new NameTag(this.tagInfo());
    this.root.add(this.tag.sprite);
    this.root.add(this.bubble.sprite);
    // selection ring
    this.ring = new THREE.Mesh(
      new THREE.PlaneGeometry(1.5, 1.5),
      new THREE.MeshBasicMaterial({ map: selectionRingTexture(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false }),
    );
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.position.y = 0.04;
    this.ring.visible = false;
    this.ring.renderOrder = 4;
    this.root.add(this.ring);
    // hit box
    this.hitBox = new THREE.Mesh(new THREE.BoxGeometry(1, 2.3, 1), new THREE.MeshBasicMaterial());
    this.hitBox.position.y = 1.15;
    this.hitBox.visible = false;
    this.hitBox.userData.agentId = agent.id;
    this.root.add(this.hitBox);
    this.y = vox.heightAt(x, z);
    this.root.position.set(x, this.y, z);
    this.home = { x, z, yaw: 0 };
    this.root.scale.setScalar(0.01);
    this.wanderAt = 8 + Math.random() * 12;
  }

  // ------------------------------------------------------------ construction
  private buildRig(): void {
    const m = this.mat;
    const part = (geo: THREE.BufferGeometry, y: number): THREE.Mesh => {
      const mesh = new THREE.Mesh(geo, m);
      mesh.position.y = y;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      return mesh;
    };
    // legs (pivot at hips)
    this.legR.position.set(-2 * PX, 12 * PX, 0);
    this.legL.position.set(2 * PX, 12 * PX, 0);
    this.legR.add(part(skinBox(4, 12, 4, SKIN_UV.leg), -6 * PX));
    this.legL.add(part(skinBox(4, 12, 4, SKIN_UV.leg), -6 * PX));
    // body
    this.body = part(skinBox(8, 12, 4, SKIN_UV.body), 18 * PX);
    // arms (pivot near shoulder)
    this.armR.position.set(-6 * PX, 22 * PX, 0);
    this.armL.position.set(6 * PX, 22 * PX, 0);
    this.armR.add(part(skinBox(4, 12, 4, SKIN_UV.arm), -4 * PX));
    this.armL.add(part(skinBox(4, 12, 4, SKIN_UV.arm), -4 * PX));
    // head (pivot at neck)
    this.head.position.set(0, 24 * PX, 0);
    this.head.add(part(skinBox(8, 8, 8, SKIN_UV.head), 4 * PX));
    this.model.add(this.legL, this.legR, this.body, this.armL, this.armR, this.head);
    // tool in right hand
    const handle = new THREE.Mesh(new THREE.BoxGeometry(PX, PX, 9 * PX), this.ownMat(new THREE.MeshLambertMaterial({ color: 0x6b4a2e })));
    handle.position.z = 3 * PX;
    const metal = this.ownMat(new THREE.MeshLambertMaterial({ color: 0xd0d2d6, map: sharedTileTexture(T.IronBlock) }));
    const pick = this.seed % 2 === 0;
    const headGeo = pick ? new THREE.BoxGeometry(PX * 1.2, 7 * PX, PX * 1.5) : new THREE.BoxGeometry(PX * 2.5, 4 * PX, PX * 2.5);
    const toolHead = new THREE.Mesh(headGeo, metal);
    toolHead.position.set(0, pick ? 0 : PX, 7.5 * PX);
    if (pick) {
      const tipA = new THREE.Mesh(new THREE.BoxGeometry(PX * 1.2, PX * 1.5, PX * 2), metal);
      tipA.position.set(0, 3.2 * PX, -0.8 * PX);
      const tipB = tipA.clone();
      tipB.position.y = -3.2 * PX;
      toolHead.add(tipA, tipB);
    }
    this.tool.add(handle, toolHead);
    this.tool.position.set(0, -10 * PX, 0.5 * PX);
    this.tool.traverse((o) => ((o as THREE.Mesh).isMesh ? ((o as THREE.Mesh).castShadow = true) : undefined));
    this.tool.visible = false;
    this.armR.add(this.tool);
  }

  private ownMat<M extends THREE.Material>(m: M): M {
    this.extraMats.push(m);
    return m;
  }

  private applySkin(spec: SkinSpec): void {
    const key = JSON.stringify(spec);
    if (key === this.skinKey) return;
    this.skinKey = key;
    this.mat.map?.dispose();
    const tex = new THREE.CanvasTexture(skinCanvas(spec, this.agent.id));
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.magFilter = THREE.NearestFilter;
    tex.minFilter = THREE.NearestFilter;
    tex.generateMipmaps = false;
    tex.flipY = false;
    this.mat.map = tex;
    this.mat.needsUpdate = true;
    // hat
    if (this.hat) {
      this.head.remove(this.hat);
      this.hat.traverse((o) => {
        const mm = o as THREE.Mesh;
        if (mm.isMesh) {
          mm.geometry.dispose();
          (mm.material as THREE.Material).dispose();
        }
      });
      this.hat = null;
    }
    const h = buildHat(spec);
    this.hat = h.group;
    this.hatHeight = h.height;
    if (this.hat) this.head.add(this.hat);
    // cape
    if (this.cape) {
      this.model.remove(this.cape);
      this.cape.traverse((o) => ((o as THREE.Mesh).isMesh ? (o as THREE.Mesh).geometry.dispose() : undefined));
      this.cape = null;
    }
    if (spec.cape) {
      const g = new THREE.Group();
      const c = new THREE.Mesh(skinBox(10, 16, 1, SKIN_UV.cape), this.mat);
      c.position.set(0, -8 * PX, -0.5 * PX);
      c.castShadow = true;
      g.add(c);
      g.position.set(0, 24 * PX, -2.1 * PX);
      this.cape = g;
      this.model.add(g);
    }
  }

  private tagInfo(): TagInfo {
    const a = this.agent;
    const sub = a.role === 'council' ? (a.model ? `${a.title} · ${a.model}` : a.title) : a.model ? `${a.model}${a.project ? ' · ' + a.project : ''}` : a.title;
    return { name: a.name, subtitle: sub, status: a.status, selected: this.selected, hovered: this.hovered, council: a.role === 'council' };
  }

  // ------------------------------------------------------------ public control
  setAgent(agent: Agent): void {
    const prevStatus = this.agent.status;
    this.agent = agent;
    this.hitBox.userData.agentId = agent.id;
    this.applySkin(agent.skin);
    this.tag.update(this.tagInfo());
    if (prevStatus !== agent.status && agent.status === 'done') this.jumpT = 0;
  }

  setSelected(sel: boolean, now: number): void {
    if (sel && !this.selected) this.lookCamUntil = now + 2.6;
    this.selected = sel;
    this.ring.visible = sel;
    this.tag.update(this.tagInfo());
  }

  setHovered(h: boolean): void {
    if (h === this.hovered) return;
    this.hovered = h;
    this.tag.update(this.tagInfo());
  }

  setHome(x: number, z: number, yaw: number, vox: VoxelWorld, focus: THREE.Vector3 | null, secondary: THREE.Vector3 | null = null): void {
    const moved = Math.hypot(x - this.home.x, z - this.home.z) > 0.3;
    this.home = { x, z, yaw };
    this.focus = focus;
    this.secondaryFocus = secondary;
    if (moved || this.path.length === 0) this.walkTo(x, z, vox);
  }

  /** place instantly (initial spawn) */
  teleportHome(vox: VoxelWorld): void {
    this.path = [];
    this.walking = false;
    this.root.position.x = this.home.x;
    this.root.position.z = this.home.z;
    this.y = vox.heightAt(this.home.x, this.home.z);
    this.root.position.y = this.y;
    this.yaw = this.targetYaw = this.home.yaw;
    this.root.rotation.y = this.yaw;
  }

  walkTo(x: number, z: number, vox: VoxelWorld): void {
    const p = this.root.position;
    if (Math.hypot(x - p.x, z - p.z) < 0.15) {
      this.path = [];
      return;
    }
    const found = vox.findPath(p.x, p.z, x, z);
    this.path = found ?? [[x, z]];
    const len = this.path.length;
    this.speed = len > 30 ? 3.6 : 2.7;
  }

  act(kind: ActionKind, now: number, dur: number): void {
    this.action = { kind, start: now, until: now + dur };
    if (kind === 'catch' || kind === 'cheer') this.jumpT = 0;
    if (kind === 'glow') this.glow = 1;
  }

  say(text: string, kind: ActivityKind, now: number): void {
    if (!text) return;
    this.bubble.show(text, kind, now);
  }

  remove(): void {
    this.removing = true;
    this.removeT = 0;
  }

  get isRemoving(): boolean {
    return this.removing;
  }

  get isWalking(): boolean {
    return this.walking;
  }

  get status(): AgentStatus {
    return this.agent.status;
  }

  /** world position of the top of the head (for overlays / effects) */
  headPos(out = new THREE.Vector3()): THREE.Vector3 {
    return out.set(this.root.position.x, this.root.position.y + (2 + this.hatHeight) * this.root.scale.y + 0.1, this.root.position.z);
  }
  chestPos(out = new THREE.Vector3()): THREE.Vector3 {
    return out.set(this.root.position.x, this.root.position.y + 1.3, this.root.position.z);
  }
  handPos(out = new THREE.Vector3()): THREE.Vector3 {
    this.armR.updateWorldMatrix(true, false);
    return out.set(0, -11 * PX, 0).applyMatrix4(this.armR.matrixWorld);
  }

  // ------------------------------------------------------------ per-frame
  update(dt: number, ctx: CharacterCtx): void {
    const now = ctx.now;
    const pos = this.root.position;
    // spawn / removal scaling
    if (this.removing) {
      this.removeT += dt;
      const s = Math.max(0.001, 1 - this.removeT / 0.45);
      this.root.scale.setScalar(s);
      if (this.removeT >= 0.45) this.removed = true;
    } else if (this.spawnT < 1) {
      this.spawnT = Math.min(1, this.spawnT + dt / 0.55);
      const k = this.spawnT;
      const c1 = 1.70158;
      const s = 1 + (c1 + 1) * Math.pow(k - 1, 3) + c1 * Math.pow(k - 1, 2);
      this.root.scale.setScalar(Math.max(0.01, s));
    }

    const status = this.agent.status;
    // ---- movement along path
    this.walking = false;
    if (this.path.length && status !== 'offline') {
      const [tx, tz] = this.path[0];
      const dx = tx - pos.x;
      const dz = tz - pos.z;
      const d = Math.hypot(dx, dz);
      const step = this.speed * dt;
      if (d <= step) {
        pos.x = tx;
        pos.z = tz;
        this.path.shift();
      } else {
        pos.x += (dx / d) * step;
        pos.z += (dz / d) * step;
      }
      if (d > 0.01) this.targetYaw = Math.atan2(dx, dz);
      this.walking = true;
      this.walkPhase += dt * this.speed * 3.4;
    } else if (this.wandering && !this.path.length) {
      // arrived at wander spot: go home after a pause
      if (now > this.wanderAt) {
        this.wandering = false;
        this.walkTo(this.home.x, this.home.z, ctx.vox);
        this.wanderAt = now + 10 + Math.random() * 18;
      }
    }
    const atHome = !this.path.length && Math.hypot(pos.x - this.home.x, pos.z - this.home.z) < 0.4;

    // idle wandering
    if (!this.walking && !this.wandering && atHome && status === 'idle' && !this.action) {
      if (this.wanderAt === 0 || now > this.wanderAt) {
        if (this.wanderAt !== 0 && Math.random() < 0.7) {
          for (let tries = 0; tries < 6; tries++) {
            const a = Math.random() * Math.PI * 2;
            const r = 1.5 + Math.random() * 2;
            const wx = Math.floor(this.home.x + Math.cos(a) * r) + 0.5;
            const wz = Math.floor(this.home.z + Math.sin(a) * r) + 0.5;
            if (ctx.vox.walkable(Math.floor(wx), Math.floor(wz)) && Math.abs(ctx.vox.heightAt(wx, wz) - this.y) <= 1) {
              this.walkTo(wx, wz, ctx.vox);
              this.wandering = true;
              this.wanderAt = now + 2 + Math.random() * 4;
              break;
            }
          }
        }
        if (!this.wandering) this.wanderAt = now + 8 + Math.random() * 14;
      }
    }
    if (status !== 'idle' && this.wandering && !this.path.length) {
      this.wandering = false;
      this.walkTo(this.home.x, this.home.z, ctx.vox);
    }

    // ---- facing when not walking
    if (!this.walking) {
      const act = this.action && now < this.action.until ? this.action : null;
      let face: THREE.Vector3 | null = null;
      if (act?.kind === 'read') face = this.secondaryFocus ?? this.focus;
      else if (act?.kind === 'hammer' || status === 'working') face = this.focus;
      if (face && atHome) this.targetYaw = Math.atan2(face.x - pos.x, face.z - pos.z);
      else if (atHome) this.targetYaw = this.home.yaw;
    }
    const dy = wrapAngle(this.targetYaw - this.yaw);
    this.yaw += dy * Math.min(1, dt * 8);
    this.root.rotation.y = this.yaw;

    // ---- terrain height (smooth step up/down)
    const gy = ctx.vox.heightAt(pos.x, pos.z);
    this.y += (gy - this.y) * Math.min(1, dt * 12);
    let bob = 0;

    // ---- pose
    const action = this.action && now < this.action.until ? this.action : null;
    if (this.action && now >= this.action.until) this.action = null;
    let pose: Pose = this.walking ? 'walk' : (status as Pose);
    if (status === 'offline') pose = 'offline';
    const t = now + (this.seed % 1000) / 137;
    const P = this.pose;
    P.reset();
    this.tool.visible = false;
    switch (pose) {
      case 'walk': {
        const s = Math.sin(this.walkPhase);
        P.legR = s * 0.75;
        P.legL = -s * 0.75;
        P.armR = -s * 0.6;
        P.armL = s * 0.6;
        bob = Math.abs(Math.cos(this.walkPhase)) * 0.06;
        P.cape = 0.25 + Math.abs(s) * 0.25;
        break;
      }
      case 'idle':
        P.armRz = 0.04 + Math.sin(t * 1.3) * 0.03;
        P.armLz = -0.04 - Math.sin(t * 1.3) * 0.03;
        P.bodyY = Math.sin(t * 2) * 0.008;
        break;
      case 'working': {
        const council = this.agent.role === 'council';
        if (council) {
          // gesturing over the table
          P.armR = -1.1 + Math.sin(t * 3) * 0.25;
          P.armL = -0.9 + Math.sin(t * 3 + 1.4) * 0.25;
          P.headPitch = 0.25;
        } else {
          this.tool.visible = true;
          const sw = Math.max(0, Math.sin(t * 8));
          P.armR = -0.6 - sw * 1.4;
          P.armL = -0.2;
          P.headPitch = 0.2;
        }
        break;
      }
      case 'thinking':
        P.armR = -1.85;
        P.armRz = 0.55;
        P.armL = -0.5;
        P.armLz = -0.35;
        P.headPitch = -0.12 + Math.sin(t * 0.8) * 0.05;
        P.headRoll = 0.12;
        break;
      case 'waiting': {
        P.sit = 1;
        P.legR = -1.45 + Math.max(0, Math.sin(t * 7)) * 0.18;
        P.legL = -1.45;
        P.legRz = 0.1;
        P.legLz = -0.1;
        P.armR = -0.55;
        P.armL = -0.55;
        P.headPitch = Math.sin(t * 0.6) * 0.1;
        break;
      }
      case 'done':
        P.armR = -0.2;
        P.armL = -0.2;
        if (this.jumpT < 0 && Math.random() < dt * 0.35) this.jumpT = 0;
        break;
      case 'error':
        P.headPitch = 0.6;
        P.lean = 0.18;
        P.armR = -0.25;
        P.armL = -0.25;
        P.armRz = 0.12;
        P.armLz = -0.12;
        break;
      case 'offline':
        P.headPitch = 0.3;
        break;
    }
    // action overlays
    if (action && !this.walking) {
      const at = now - action.start;
      switch (action.kind) {
        case 'hammer': {
          this.tool.visible = this.agent.role !== 'council';
          const sw = Math.max(0, Math.sin(at * 11));
          P.armR = -0.5 - sw * 1.6;
          P.headPitch = 0.3;
          P.sit = 0;
          P.legR = P.legL = 0;
          break;
        }
        case 'read':
          P.armR = -1.0 + Math.sin(at * 2) * 0.05;
          P.armL = -1.0 + Math.sin(at * 2 + 1) * 0.05;
          P.armRz = 0.25;
          P.armLz = -0.25;
          P.headPitch = 0.35;
          break;
        case 'cast':
          P.armR = -2.4 + Math.sin(at * 6) * 0.2;
          P.armL = -2.4 - Math.sin(at * 6) * 0.2;
          P.armRz = -0.2;
          P.armLz = 0.2;
          P.headPitch = -0.2;
          break;
        case 'give':
          P.armR = -1.4;
          P.armL = -1.4;
          break;
        case 'catch':
        case 'cheer':
          P.armR = -2.9;
          P.armL = -2.9;
          P.armRz = -0.25;
          P.armLz = 0.25;
          P.sit = 0;
          P.legR = P.legL = 0;
          break;
        case 'glow':
          P.armR = -2.2;
          P.armRz = 0.1;
          break;
      }
    }
    // jump
    let jump = 0;
    if (this.jumpT >= 0) {
      this.jumpT += dt;
      const k = this.jumpT / 0.45;
      if (k >= 1) this.jumpT = -1;
      else {
        jump = Math.sin(k * Math.PI) * 0.55;
        P.armR = Math.min(P.armR, -2.6);
        P.armL = Math.min(P.armL, -2.6);
        P.sit = 0;
      }
    }

    // head look: at camera when freshly selected, otherwise look around idly
    let hy = 0;
    let hp = P.headPitch;
    if (now < this.lookCamUntil) {
      ctx.camera.getWorldPosition(_v);
      this.headPos(_w);
      const want = Math.atan2(_v.x - pos.x, _v.z - pos.z);
      hy = Math.max(-1.1, Math.min(1.1, wrapAngle(want - this.yaw)));
      const horiz = Math.hypot(_v.x - _w.x, _v.z - _w.z);
      hp = Math.max(-0.6, Math.min(0.5, -Math.atan2(_v.y - _w.y, horiz)));
    } else if (pose === 'idle' || pose === 'waiting' || pose === 'done') {
      if (now > this.lookAroundAt) {
        this.lookAround = (Math.random() - 0.5) * 1.6;
        this.lookAroundAt = now + 2 + Math.random() * 4;
      }
      hy = this.lookAround;
    }
    this.headYaw += (hy - this.headYaw) * Math.min(1, dt * 5);
    this.headPitch += (hp - this.headPitch) * Math.min(1, dt * 6);

    // apply
    const lerpK = Math.min(1, dt * 14);
    const ap = (g: THREE.Object3D, x: number, z = 0): void => {
      g.rotation.x += (x - g.rotation.x) * lerpK;
      g.rotation.z += (z - g.rotation.z) * lerpK;
    };
    ap(this.armR, P.armR, P.armRz);
    ap(this.armL, P.armL, P.armLz);
    ap(this.legR, P.legR, P.legRz);
    ap(this.legL, P.legL, P.legLz);
    this.head.rotation.y = this.headYaw;
    this.head.rotation.x = this.headPitch;
    this.head.rotation.z += (P.headRoll - this.head.rotation.z) * lerpK;
    if (this.cape) this.cape.rotation.x += (P.cape + (P.sit ? 0.1 : 0) - this.cape.rotation.x) * lerpK;
    this.model.rotation.x += (P.lean - this.model.rotation.x) * lerpK;
    const sitY = P.sit ? -0.62 : 0;
    this.model.position.y += (sitY + P.bodyY - this.model.position.y) * Math.min(1, dt * 10);
    pos.y = this.y + bob + jump;

    // ---- status particles
    this.fxTimer -= dt;
    if (this.fxTimer <= 0 && !this.walking && !this.removing) {
      this.fxTimer = 1.1 + Math.random() * 0.8;
      const hp3 = this.headPos(_w);
      switch (status) {
        case 'thinking':
          ctx.fx.thought(_v.set(hp3.x + 0.2, hp3.y + 0.1, hp3.z));
          break;
        case 'waiting':
          if (Math.random() < 0.5) ctx.fx.hourglass(_v.set(hp3.x, hp3.y - 0.4, hp3.z));
          break;
        case 'done':
          ctx.fx.sparkle(_v.set(pos.x, pos.y + 0.2, pos.z), 5, 0x6dff8a, 0.5);
          break;
        case 'error':
          ctx.fx.smoke(_v.set(pos.x, hp3.y - 0.1, pos.z), 3, 0xc0302a);
          break;
        case 'working':
          if (this.focus && this.agent.role !== 'council' && Math.random() < 0.6) ctx.fx.blockBreak(this.focus, 0x9a7a52);
          if (this.agent.role === 'council') ctx.fx.runes(_v.set(pos.x, pos.y + 1.2, pos.z), 3, 0xc49bff, 0.8);
          break;
      }
    }

    // ---- opacity (offline fade)
    const targetOpacity = status === 'offline' ? 0.35 : 1;
    this.opacity += (targetOpacity - this.opacity) * Math.min(1, dt * 2);
    const fading = this.opacity < 0.99;
    if (this.mat.transparent !== fading || (fading && Math.abs(this.mat.opacity - this.opacity) > 0.005)) {
      // body, cape, hat and tool fade together
      this.model.traverse((o) => {
        const m = o as THREE.Mesh;
        if (!m.isMesh) return;
        const mat = m.material as THREE.MeshLambertMaterial;
        if (mat.transparent !== fading) {
          mat.transparent = fading;
          mat.depthWrite = !fading;
          if (mat === this.mat) mat.alphaTest = fading ? 0 : 0.5;
          mat.needsUpdate = true;
        }
        mat.opacity = this.opacity;
      });
    }
    // emissive glow (delegation / hover)
    this.glow = Math.max(0, this.glow - dt * 0.7);
    const g = this.glow * (0.6 + Math.sin(now * 12) * 0.2) + (this.hovered ? 0.12 : 0);
    this.mat.emissive.setRGB(g * 0.75, g * 0.5, g * 1.0);

    // ---- labels
    ctx.camera.getWorldPosition(_v);
    const dist = _v.distanceTo(pos);
    const f = Math.max(0.9, Math.min(1.7, dist / 22));
    const s = this.root.scale.y || 1;
    const tagY = 2 + this.hatHeight + 0.18 + (P.sit ? -0.62 : 0);
    const ts = this.tag.sprite;
    ts.scale.set((ts.userData.baseW * f) / s, (ts.userData.baseH * f) / s, 1);
    ts.position.y = tagY;
    const fade = this.selected || this.hovered ? 1 : 1 - Math.max(0, Math.min(0.7, (dist - 60) / 60));
    ts.material.opacity = fade * (status === 'offline' ? 0.6 : 1);
    ts.visible = fade > 0.02;
    const bs = this.bubble.update(now);
    this.bubble.sprite.material.opacity *= this.selected || this.hovered ? 1 : 1 - Math.max(0, Math.min(1, (dist - 55) / 30));
    if (bs > 0) {
      const b = this.bubble.sprite;
      b.scale.set((b.userData.baseW * f * bs) / s, (b.userData.baseH * f * bs) / s, 1);
      b.position.y = tagY + ts.userData.baseH * f + 0.06;
    }
    // ring
    if (this.ring.visible) {
      this.ring.rotation.z = now * 0.8;
      const k = 1 + Math.sin(now * 4) * 0.06;
      this.ring.scale.set(k, k, 1);
      this.ring.position.y = 0.04 - (P.sit ? 0 : 0);
    }
  }

  private pose = new PoseTarget();

  dispose(): void {
    this.root.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) m.geometry.dispose();
    });
    this.mat.map?.dispose();
    this.mat.dispose();
    for (const m of this.extraMats) m.dispose();
    if (this.hat)
      this.hat.traverse((o) => {
        const mm = o as THREE.Mesh;
        if (mm.isMesh) (mm.material as THREE.Material).dispose();
      });
    (this.ring.material as THREE.Material).dispose();
    (this.hitBox.material as THREE.Material).dispose();
    this.tag.dispose();
    this.bubble.dispose();
    this.root.removeFromParent();
  }
}

class PoseTarget {
  armR = 0;
  armL = 0;
  armRz = 0;
  armLz = 0;
  legR = 0;
  legL = 0;
  legRz = 0;
  legLz = 0;
  headPitch = 0;
  headRoll = 0;
  lean = 0;
  sit = 0;
  bodyY = 0;
  cape = 0.08;
  reset(): void {
    this.armR = this.armL = this.armRz = this.armLz = 0;
    this.legR = this.legL = this.legRz = this.legLz = 0;
    this.headPitch = this.headRoll = this.lean = this.sit = this.bodyY = 0;
    this.cape = 0.08;
  }
}

// ------------------------------------------------------------ hats
function buildHat(spec: SkinSpec): { group: THREE.Group | null; height: number } {
  if (spec.hat === 'none') return { group: null, height: 0 };
  const g = new THREE.Group();
  const top = 8 * PX; // top of head, relative to neck pivot
  const noise = hatNoise();
  const matOf = (color: THREE.ColorRepresentation, map: THREE.Texture | null = noise, emissive = 0): THREE.MeshLambertMaterial =>
    new THREE.MeshLambertMaterial({ color, map, emissive: new THREE.Color(color).multiplyScalar(emissive) });
  const box = (w: number, h: number, d: number, x: number, y: number, z: number, m: THREE.Material): THREE.Mesh => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w * PX, h * PX, d * PX), m);
    mesh.position.set(x * PX, y * PX, z * PX);
    mesh.castShadow = true;
    g.add(mesh);
    return mesh;
  };
  const acc = hex(spec.accent);
  const accent = new THREE.Color(`rgb(${acc[0]},${acc[1]},${acc[2]})`);
  let height = 0;
  switch (spec.hat) {
    case 'crown': {
      const gold = matOf(0xffffff, sharedTileTexture(T.Gold), 0.08);
      const t = 8 - 0.5;
      // band (slightly larger than the head)
      box(9, 2.5, 1, 0, t, 4, gold);
      box(9, 2.5, 1, 0, t, -4, gold);
      box(1, 2.5, 7, 4, t, 0, gold);
      box(1, 2.5, 7, -4, t, 0, gold);
      // points
      for (const [x, z] of [[-4, 4], [0, 4], [4, 4], [-4, -4], [0, -4], [4, -4], [4, 0], [-4, 0]]) box(1, 2, 1, x, t + 2.2, z, gold);
      // gems
      const red = matOf(0xe0283a, null, 0.35);
      const blue = matOf(0x2a8cff, null, 0.35);
      box(1.2, 1.2, 0.6, 0, t, 4.6, red);
      box(0.6, 1.2, 1.2, 4.6, t, 0, blue);
      box(0.6, 1.2, 1.2, -4.6, t, 0, blue);
      height = 4 * PX;
      break;
    }
    case 'wizard': {
      const sh = hex(spec.shirt);
      const hatCol = shade(sh, 0.8);
      const m = matOf(`rgb(${hatCol[0]},${hatCol[1]},${hatCol[2]})`);
      const band = matOf(accent);
      box(12, 1, 12, 0, top / PX + 0.5, 0, m);
      box(8.4, 1.2, 8.4, 0, top / PX + 1.4, 0, band);
      const tiers = [
        [8, 3, 0],
        [6, 3, -0.5],
        [4, 3, -1.2],
        [2.5, 3, -2.2],
        [1.5, 2, -3.2],
      ];
      let y = top / PX + 2;
      tiers.forEach(([w, h, z]) => {
        box(w, h, w, 0, y + h / 2, z, m);
        y += h;
      });
      const star = matOf(0xffe070, null, 0.6);
      box(1, 1, 0.5, -1, top / PX + 4, 4.1, star);
      height = (y - top / PX) * PX;
      break;
    }
    case 'hood': {
      const c = hex(spec.cape ?? spec.shirt);
      const m = matOf(`rgb(${c[0]},${c[1]},${c[2]})`);
      const trim = matOf(accent);
      box(9.4, 1.2, 9.4, 0, top / PX + 0.4, 0, m); // crown
      box(9.4, 9, 1, 0, 4, -4.6, m); // back
      box(1, 9, 9.4, 4.6, 4, 0, m);
      box(1, 9, 9.4, -4.6, 4, 0, m);
      box(9.6, 1, 1.2, 0, top / PX + 0.2, 4.4, trim); // front rim
      box(1.2, 8, 1.2, 4.6, 4, 4.4, trim);
      box(1.2, 8, 1.2, -4.6, 4, 4.4, trim);
      box(4, 2, 2, 0, 8.6, -4.2, m); // point
      height = 1.2 * PX;
      break;
    }
    case 'helmet': {
      const m = matOf(0xdadde2, sharedTileTexture(T.IronBlock));
      box(9.2, 2, 9.2, 0, top / PX + 0.2, 0, m);
      box(9.2, 5, 1, 0, 5, -4.6, m);
      box(1, 4, 9.2, 4.6, 5.5, 0, m);
      box(1, 4, 9.2, -4.6, 5.5, 0, m);
      box(9.4, 1, 1, 0, 7, 4.6, m); // brow
      box(1, 3, 0.8, 0, 5, 4.6, m); // nose guard
      box(1.2, 2.5, 1.2, 0, top / PX + 2, 0, matOf(accent)); // plume base
      box(1, 1.5, 4, 0, top / PX + 3.5, -1, matOf(accent));
      height = 4 * PX;
      break;
    }
    case 'cap': {
      const m = matOf(accent);
      box(8.6, 2, 8.6, 0, top / PX + 0.4, 0, m);
      box(8, 0.8, 4, 0, top / PX - 0.4, 6, m);
      box(1, 1, 1, 0, top / PX + 1.8, 0, m);
      height = 2 * PX;
      break;
    }
    case 'headband': {
      const m = matOf(accent);
      const y = 6.5;
      box(8.6, 1.5, 0.6, 0, y, 4.1, m);
      box(8.6, 1.5, 0.6, 0, y, -4.1, m);
      box(0.6, 1.5, 8.6, 4.1, y, 0, m);
      box(0.6, 1.5, 8.6, -4.1, y, 0, m);
      box(1.5, 1.5, 1, 1.5, y - 0.5, -4.6, m);
      box(1, 3, 0.6, 2.5, y - 2, -4.6, m);
      height = 0;
      break;
    }
  }
  return { group: mergeByMaterial(g), height };
}

/** collapse a group of static boxes into one mesh per material (fewer draw calls) */
function mergeByMaterial(g: THREE.Group): THREE.Group {
  const byMat = new Map<THREE.Material, THREE.BufferGeometry[]>();
  g.updateMatrixWorld(true);
  for (const o of g.children) {
    const m = o as THREE.Mesh;
    if (!m.isMesh) continue;
    const geo = m.geometry.clone().applyMatrix4(m.matrix);
    m.geometry.dispose();
    const mat = m.material as THREE.Material;
    if (!byMat.has(mat)) byMat.set(mat, []);
    byMat.get(mat)!.push(geo);
  }
  const out = new THREE.Group();
  for (const [mat, geos] of byMat) {
    const merged = mergeGeometries(geos, false);
    geos.forEach((x) => x.dispose());
    if (!merged) continue;
    const mesh = new THREE.Mesh(merged, mat);
    mesh.castShadow = true;
    out.add(mesh);
  }
  return out;
}
