// Agent Realm — 3D voxel world renderer. Public API consumed by src/main.ts.
import * as THREE from 'three';
import type { Agent, Activity, Mission } from '../../shared/protocol';
import { VoxelWorld, worldMaterials, disposeWorldMaterials } from './terrain';
import { CouncilHallFx, Plot, makeTaskBoard, makeLamps, stampCouncilHall, stampVillage, disposeGroup } from './buildings';
import { Character } from './character';
import { Effects } from './effects';
import { Sky } from './sky';
import { CameraRig } from './camera';
import { councilSeats, PLOTS, PLOT_HALF, PLACES, PLAZA, SEA, VILLAGE_Y, HALL, HALL_Y, yawTo } from './layout';
import { T } from './blocks';
import { tileTexture } from './textures';

export type Place = 'overview' | 'council' | 'village';

const _v = new THREE.Vector3();
const _ndc = new THREE.Vector3();

export class World {
  onSelect: (id: string | null) => void = () => {};
  onHover: (id: string | null) => void = () => {};

  private container: HTMLElement;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private rig: CameraRig;
  private sky = new Sky();
  private vox = new VoxelWorld();
  private terrain: THREE.Group;
  private water: THREE.Mesh;
  private waterTime = { value: 0 };
  private oceanFloor: THREE.Mesh;
  private hall = new CouncilHallFx();
  private taskBoard: THREE.Group;
  private lamps: THREE.Group;
  private plazaLight: THREE.PointLight;
  private fx: Effects;
  private chars = new Map<string, Character>();
  private dying: Character[] = [];
  private plots = new Map<string, Plot>(); // agentId → plot
  private slotOwner = new Map<number, string>(); // plot index → agentId
  private firstSync = true;
  private selectedId: string | null = null;
  private hoveredId: string | null = null;
  private quality: 'high' | 'low' = 'high';
  private now = 0;
  private lastTs = 0;
  private raf = 0;
  private running = false;
  private width = 1;
  private height = 1;
  private ro: ResizeObserver;
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2();
  private pointerInside = false;
  private pointerDirty = false;
  private downAt: { x: number; y: number; t: number } | null = null;
  private ambientT = 0;
  private disposed = false;

  constructor(container: HTMLElement) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    const r = this.renderer;
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 1.05;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFShadowMap;
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const canvas = r.domElement;
    canvas.style.display = 'block';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.touchAction = 'none';
    canvas.style.outline = 'none';
    container.appendChild(canvas);

    this.rig = new CameraRig(canvas);
    this.fx = new Effects();

    // --- world generation (deterministic)
    this.vox.generate();
    this.vox.layVillage();
    stampCouncilHall(this.vox);
    stampVillage(this.vox);
    this.vox.decorate();
    this.vox.computeWalk();
    this.terrain = this.vox.buildMeshes();

    // --- scene graph
    const s = this.scene;
    s.fog = this.sky.fog;
    s.add(this.sky.group, this.sky.sun, this.sky.sun.target, this.sky.hemi);
    this.sky.sun.target.position.set(0, 12, 0);
    s.add(this.terrain);
    this.water = this.makeWater();
    s.add(this.water);
    this.oceanFloor = this.makeOceanFloor();
    s.add(this.oceanFloor);
    s.add(this.hall.group);
    this.taskBoard = makeTaskBoard();
    s.add(this.taskBoard);
    this.lamps = makeLamps();
    s.add(this.lamps);
    this.plazaLight = new THREE.PointLight(0xffb45a, 0, 18, 1.6);
    this.plazaLight.position.set(PLAZA.x, VILLAGE_Y + 4.5, PLAZA.z);
    s.add(this.plazaLight);
    s.add(this.fx.group);

    this.sky.snap();
    this.focusPlace('overview', true);

    // --- events
    canvas.addEventListener('pointerdown', this.onPointerDown);
    canvas.addEventListener('pointerup', this.onPointerUp);
    canvas.addEventListener('pointermove', this.onPointerMove);
    canvas.addEventListener('pointerleave', this.onPointerLeave);
    document.addEventListener('visibilitychange', this.onVisibility);
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(container);
    this.resize();
    this.start();
  }

  // ================================================================ public API
  setAgents(agents: Agent[]): void {
    const seen = new Set<string>();
    for (const a of agents) seen.add(a.id);
    // removals
    for (const [id, c] of this.chars) {
      if (seen.has(id)) continue;
      this.fx.poof(c.root.position.clone(), 26);
      c.remove();
      this.dying.push(c);
      this.chars.delete(id);
      this.freePlot(id);
      if (this.selectedId === id) this.selectedId = null;
    }
    // create / update
    const fresh: Character[] = [];
    for (const a of agents) {
      let c = this.chars.get(a.id);
      if (!c) {
        c = new Character(a, PLAZA.x, PLAZA.z, this.vox);
        this.chars.set(a.id, c);
        this.scene.add(c.root);
        fresh.push(c);
        if (a.id === this.selectedId) c.setSelected(true, this.now);
      } else c.setAgent(a);
    }
    // plots: release plots of agents that are no longer workers
    for (const a of agents) if (a.role !== 'worker') this.freePlot(a.id);
    // allocate plots for workers in id order (deterministic on first sync)
    const workers = agents.filter((a) => a.role === 'worker').sort((p, q) => (p.id < q.id ? -1 : p.id > q.id ? 1 : 0));
    let plantsDirty = false;
    for (const w of workers) {
      if (this.plots.has(w.id)) continue;
      const slot = PLOTS.find((p) => !this.slotOwner.has(p.index));
      if (!slot) continue;
      if (this.vox.clearPlants(slot.cx - PLOT_HALF, slot.cz - PLOT_HALF, slot.cx + PLOT_HALF, slot.cz + PLOT_HALF)) plantsDirty = true;
      const plot = new Plot(slot, this.vox, w.id, w.source, (w.stats?.toolCalls ?? 0) % 60);
      this.plots.set(w.id, plot);
      this.slotOwner.set(slot.index, w.id);
      this.scene.add(plot.group);
      if (!this.firstSync) this.fx.sparkle(plot.world(0, 0, 0.5), 20, 0xfff2a0, 3);
    }
    if (plantsDirty) this.rebuildPlants();
    // homes
    const council = agents.filter((a) => a.role === 'council').sort((p, q) => (p.id < q.id ? -1 : p.id > q.id ? 1 : 0));
    const seats = councilSeats(council.length);
    const tableCenter = new THREE.Vector3(HALL.x, HALL_Y + 1.6, HALL.z);
    council.forEach((a, i) => {
      const c = this.chars.get(a.id)!;
      const seat = seats[i];
      c.setHome(seat.x, seat.z, seat.facing, this.vox, tableCenter, tableCenter);
    });
    let overflow = 0;
    for (const w of workers) {
      const c = this.chars.get(w.id)!;
      const plot = this.plots.get(w.id);
      if (plot) {
        const h = plot.home;
        c.setHome(h.x, h.z, h.yaw, this.vox, plot.buildFocus, plot.stationPos);
      } else {
        const a = (overflow++ * 2.4) % (Math.PI * 2);
        const x = PLAZA.x + Math.cos(a) * 3.2;
        const z = PLAZA.z + Math.sin(a) * 3.2;
        c.setHome(x, z, yawTo(PLAZA.x - x, PLAZA.z - z), this.vox, null);
      }
    }
    for (const c of fresh) {
      c.teleportHome(this.vox);
      if (!this.firstSync) this.fx.poof(_v.set(c.home.x, this.vox.heightAt(c.home.x, c.home.z), c.home.z).clone(), 28);
    }
    this.firstSync = false;
  }

  onActivity(a: Activity): void {
    const c = this.chars.get(a.agentId);
    if (!c) return;
    const now = this.now;
    c.say(a.text, a.kind, now);
    const plot = this.plots.get(a.agentId);
    const head = c.headPos(new THREE.Vector3());
    const chest = c.chestPos(new THREE.Vector3());
    switch (a.kind) {
      case 'edit': {
        c.act('hammer', now, 1.3);
        if (plot) {
          const res = plot.placeBlock();
          if (res.reset) {
            this.fx.sparkle(res.pos, 40, 0xfff2a0, 2.2);
            this.fx.firework(res.pos.clone());
          } else {
            this.fx.blockBreak(res.pos, 0xc8a878);
            this.fx.sparkle(res.pos, 5, 0xffffff, 0.5);
          }
          c.focus = plot.buildFocus;
        } else this.fx.blockBreak(chest.clone().setY(chest.y - 0.4), 0xc8a878);
        break;
      }
      case 'bash':
      case 'tool': {
        c.act('hammer', now, 0.9);
        const at = plot ? plot.stationPos : c.handPos(new THREE.Vector3());
        this.fx.sparks(at, a.kind === 'bash' ? 18 : 8, a.kind === 'bash' ? [0xff2a1a, 0xff6a2a, 0xffd04a] : [0x9ad0a0, 0xffffff]);
        break;
      }
      case 'read':
      case 'search': {
        c.act('read', now, 2.2);
        const at = plot ? plot.secondaryPos : chest;
        this.fx.pages(at, a.kind === 'search' ? 4 : 6);
        break;
      }
      case 'web':
        c.act('cast', now, 1.4);
        this.fx.portal(chest);
        break;
      case 'think':
        this.fx.thought(head.add(_v.set(0.2, 0.1, 0)));
        break;
      case 'plan':
        c.act('cast', now, 1.2);
        this.fx.runes(chest, 10, 0xffd04a);
        break;
      case 'delegate':
        c.act('glow', now, 1.6);
        this.fx.runes(chest, 14, 0xc49bff, 1.4);
        break;
      case 'review':
        c.act('read', now, 1.6);
        this.fx.pages(chest, 3);
        this.fx.runes(chest, 6, 0x5fe8ff);
        break;
      case 'message':
        this.fx.notes(head.clone());
        break;
      case 'complete':
        c.act('cheer', now, 1.2);
        this.fx.firework(c.root.position.clone().add(_v.set(0, 1, 0)));
        this.fx.xpOrbs(c.root.position.clone().add(_v.set(0, 1.5, 0)), c.root.position.clone().add(_v.set(0, 1, 0)), 12);
        this.fx.check(head.clone().add(_v.set(0, 0.4, 0)));
        break;
      case 'error':
        this.fx.smoke(head.clone().add(_v.set(0, -0.3, 0)), 14, 0xc0302a);
        this.fx.smoke(chest, 6, 0x303030);
        break;
      case 'system':
        break;
    }
  }

  delegate(fromId: string, toId: string): void {
    const from = this.chars.get(fromId);
    const to = this.chars.get(toId);
    if (!from || !to) return;
    from.act('cast', this.now, 1.2);
    this.fx.runes(from.chestPos(new THREE.Vector3()), 10, 0xc49bff);
    const start = from.handPos(new THREE.Vector3()).add(_v.set(0, 0.4, 0));
    this.fx.flyScroll(
      start,
      () => (this.chars.get(toId) ? to.chestPos(new THREE.Vector3()) : null),
      () => {
        to.act('catch', this.now, 0.7);
      },
    );
  }

  deliver(fromId: string, toId: string): void {
    const from = this.chars.get(fromId);
    const to = this.chars.get(toId);
    if (!from || !to) return;
    from.act('give', this.now, 0.9);
    const start = from.chestPos(new THREE.Vector3()).add(_v.set(0, 0.3, 0));
    this.fx.flyChest(
      start,
      () => (this.chars.get(toId) ? to.chestPos(new THREE.Vector3()) : null),
      () => {
        to.act('glow', this.now, 1.2);
        this.fx.sparkle(to.chestPos(new THREE.Vector3()), 14, 0xffd04a, 0.6);
      },
    );
  }

  setMission(m: Mission | null): void {
    this.hall.setMission(m ? m.status : null);
  }

  focusAgent(id: string | null): void {
    if (!id) {
      this.rig.follow(null);
      return;
    }
    const c = this.chars.get(id);
    if (!c) return;
    this.rig.follow(() => {
      const cc = this.chars.get(id);
      if (!cc) return null;
      return cc.root.position.clone().add(_v.set(0, 1.2, 0));
    });
  }

  focusPlace(p: Place, instant = false): void {
    this.rig.follow(null);
    const place = PLACES[p] ?? PLACES.overview;
    const target = new THREE.Vector3(...place.target);
    const pos = target.clone().add(new THREE.Vector3(...place.offset));
    if (instant) this.rig.set(pos, target);
    else this.rig.flyTo(target, pos, 1.8);
  }

  setSelected(id: string | null): void {
    this.selectedId = id;
    for (const [cid, c] of this.chars) c.setSelected(cid === id, this.now);
  }

  getScreenPosition(id: string): { x: number; y: number; visible: boolean } | null {
    const c = this.chars.get(id);
    if (!c) return null;
    c.headPos(_ndc).add(_v.set(0, 0.35, 0));
    const cam = this.rig.camera;
    _ndc.project(cam);
    const inFront = _ndc.z > -1 && _ndc.z < 1;
    const x = ((_ndc.x + 1) / 2) * this.width;
    const y = ((1 - _ndc.y) / 2) * this.height;
    const visible = inFront && _ndc.x >= -1.05 && _ndc.x <= 1.05 && _ndc.y >= -1.05 && _ndc.y <= 1.05;
    return { x, y, visible };
  }

  setTimeMode(mode: 'auto' | 'day' | 'night'): void {
    this.sky.setMode(mode);
  }

  setQuality(q: 'high' | 'low'): void {
    if (q === this.quality) return;
    this.quality = q;
    const high = q === 'high';
    this.renderer.setPixelRatio(high ? Math.min(window.devicePixelRatio || 1, 2) : 1);
    this.renderer.shadowMap.enabled = high;
    this.sky.sun.castShadow = high;
    this.fx.density = high ? 1 : 0.35;
    this.scene.traverse((o) => {
      const m = (o as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
      if (!m) return;
      (Array.isArray(m) ? m : [m]).forEach((mm) => (mm.needsUpdate = true));
    });
    this.resize();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.stop();
    const canvas = this.renderer.domElement;
    canvas.removeEventListener('pointerdown', this.onPointerDown);
    canvas.removeEventListener('pointerup', this.onPointerUp);
    canvas.removeEventListener('pointermove', this.onPointerMove);
    canvas.removeEventListener('pointerleave', this.onPointerLeave);
    document.removeEventListener('visibilitychange', this.onVisibility);
    this.ro.disconnect();
    for (const c of this.chars.values()) c.dispose();
    for (const c of this.dying) c.dispose();
    for (const p of this.plots.values()) p.dispose();
    this.chars.clear();
    this.plots.clear();
    this.fx.dispose();
    this.hall.dispose();
    this.sky.dispose();
    disposeGroup(this.terrain);
    disposeGroup(this.taskBoard);
    disposeGroup(this.lamps);
    const pools = this.lamps.getObjectByName('pools') as THREE.Mesh | undefined;
    if (pools) {
      const pm = pools.material as THREE.MeshBasicMaterial;
      pm.map?.dispose();
      pm.dispose();
    }
    const board = this.taskBoard.children.filter((o) => (o as THREE.Mesh).isMesh) as THREE.Mesh[];
    for (const b of board) {
      const bm = b.material as THREE.MeshLambertMaterial;
      if (bm !== worldMaterials().solid) {
        bm.map?.dispose();
        bm.dispose();
      }
    }
    for (const m of [this.water, this.oceanFloor]) {
      m.geometry.dispose();
      const mat = m.material as THREE.MeshLambertMaterial;
      mat.map?.dispose();
      mat.dispose();
    }
    disposeWorldMaterials();
    this.rig.dispose();
    this.renderer.dispose();
    canvas.remove();
  }

  // ================================================================ internals
  private freePlot(id: string): void {
    const p = this.plots.get(id);
    if (!p) return;
    this.slotOwner.delete(p.slot.index);
    this.plots.delete(id);
    this.fx.poof(p.world(0, 0, 0.5), 16, 0xd8d0c0);
    p.dispose();
  }

  private rebuildPlants(): void {
    const old = this.terrain.getObjectByName('plants');
    if (old) {
      this.terrain.remove(old);
      if ((old as THREE.Mesh).isMesh) (old as THREE.Mesh).geometry.dispose();
    }
    this.terrain.add(this.vox.buildPlantMesh());
  }

  private makeWater(): THREE.Mesh {
    const tex = tileTexture(T.Water, 1);
    const size = 900;
    tex.repeat.set(size, size);
    const mat = new THREE.MeshPhongMaterial({
      map: tex,
      color: 0xbfd8ff,
      transparent: true,
      opacity: 0.8,
      shininess: 80,
      specular: 0x557799,
      depthWrite: false,
    });
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = this.waterTime;
      shader.vertexShader = 'varying vec3 vWPos;\n' + shader.vertexShader.replace('#include <fog_vertex>', '#include <fog_vertex>\n vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;');
      shader.fragmentShader =
        'uniform float uTime;\nvarying vec3 vWPos;\n' +
        shader.fragmentShader.replace(
          '#include <map_fragment>',
          `#include <map_fragment>
          float w = sin(vWPos.x * 0.9 + uTime * 1.3) * sin(vWPos.z * 0.7 - uTime * 1.1) + sin((vWPos.x + vWPos.z) * 0.35 + uTime * 0.7) * 0.5;
          diffuseColor.rgb *= 0.9 + w * 0.08;
          vec2 cell = floor(vWPos.xz * 4.0);
          float h = fract(sin(dot(cell, vec2(12.9898, 78.233))) * 43758.5453);
          diffuseColor.rgb += step(0.994, h) * (0.5 + 0.5 * sin(uTime * 3.0 + h * 40.0)) * 0.3;
          float shore = smoothstep(46.0, 58.0, length(vWPos.xz));
          diffuseColor.a = mix(diffuseColor.a, 0.92, shore);`,
        );
    };
    const geo = new THREE.PlaneGeometry(size, size);
    geo.rotateX(-Math.PI / 2);
    const m = new THREE.Mesh(geo, mat);
    m.position.y = SEA + 0.85;
    m.receiveShadow = true;
    m.renderOrder = 1;
    return m;
  }

  private makeOceanFloor(): THREE.Mesh {
    const tex = tileTexture(T.Sand, 1);
    const size = 900;
    tex.repeat.set(size, size);
    const mat = new THREE.MeshLambertMaterial({ map: tex, color: 0xa89a78 });
    const geo = new THREE.PlaneGeometry(size, size);
    geo.rotateX(-Math.PI / 2);
    const m = new THREE.Mesh(geo, mat);
    m.position.y = SEA - 4 - 0.02;
    m.receiveShadow = true;
    return m;
  }

  private resize(): void {
    const w = Math.max(1, this.container.clientWidth);
    const h = Math.max(1, this.container.clientHeight);
    this.width = w;
    this.height = h;
    this.renderer.setSize(w, h, false);
    this.rig.resize(w, h);
    this.fx.setScale(h * this.renderer.getPixelRatio(), this.rig.camera.fov);
  }

  private start(): void {
    if (this.running || this.disposed) return;
    this.running = true;
    this.lastTs = performance.now();
    this.raf = requestAnimationFrame(this.frame);
  }

  private stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  private onVisibility = (): void => {
    if (document.hidden) this.stop();
    else this.start();
  };

  private frame = (ts: number): void => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.frame);
    const dt = Math.min(0.05, Math.max(0, (ts - this.lastTs) / 1000));
    this.lastTs = ts;
    this.step(dt);
    this.renderer.render(this.scene, this.rig.camera);
  };

  /** advance the simulation (exposed for tests / previews via frame) */
  private step(dt: number): void {
    this.now += dt;
    const now = this.now;
    this.rig.update(dt);
    const cam = this.rig.camera;
    this.sky.update(dt, cam.position);
    const night = this.sky.night;
    this.waterTime.value = now;
    const wm = this.water.material as THREE.MeshPhongMaterial;
    if (wm.map) wm.map.offset.set(now * 0.02, now * 0.013);
    // lantern glow brighter at night
    const g = 1.05 + night * 0.9;
    worldMaterials().glow.color.setRGB(g * 1.1, g, g * 0.85);
    this.plazaLight.intensity = night * 14 * (0.9 + Math.sin(now * 11) * 0.05);
    const pools = this.lamps.getObjectByName('pools') as THREE.Mesh | undefined;
    if (pools) {
      const pm = pools.material as THREE.MeshBasicMaterial;
      pm.opacity = Math.max(0, night - 0.15) * 0.85 * (0.94 + Math.sin(now * 9) * 0.03);
      pools.visible = pm.opacity > 0.01;
    }
    const day = 1 - night * 0.62;
    wm.color.setRGB(0.75 * day, 0.85 * day, 1.0 * day);
    (this.oceanFloor.material as THREE.MeshLambertMaterial).color.setRGB(0.66 * day, 0.6 * day, 0.47 * day);
    this.hall.update(dt, now, night);
    // characters
    const ctx = { vox: this.vox, fx: this.fx, camera: cam, now, night };
    for (const c of this.chars.values()) c.update(dt, ctx);
    for (let i = this.dying.length - 1; i >= 0; i--) {
      const c = this.dying[i];
      c.update(dt, ctx);
      if (c.removed) {
        c.dispose();
        this.dying.splice(i, 1);
      }
    }
    for (const p of this.plots.values()) p.update(dt);
    this.ambient(dt, night);
    this.fx.update(dt, now);
    if (this.pointerDirty) {
      this.pointerDirty = false;
      this.updateHover();
    }
  }

  private ambient(dt: number, night: number): void {
    this.ambientT += dt;
    if (this.ambientT < 0.08) return;
    this.ambientT = 0;
    // council hall: runes spiral toward the crystal while deliberating
    const lvl = this.hall.level;
    if (lvl > 0.05 && Math.random() < lvl) {
      const a = Math.random() * Math.PI * 2;
      const r = 3 + Math.random() * 3;
      this.fx.spawn(
        {
          pos: { x: HALL.x + Math.cos(a) * r, y: HALL_Y + 1.5 + Math.random() * 1.5, z: HALL.z + Math.sin(a) * r },
          home: this.hall.crystalPos,
          homeStrength: 1.8,
          vel: { x: -Math.sin(a) * 1.5, y: 0.4, z: Math.cos(a) * 1.5 },
          color: this.hall.tint.clone(),
          size: 0.18,
          sizeEnd: 0.06,
          life: 2.2,
          drag: 0.4,
          tile: 4 + Math.floor(Math.random() * 4),
        },
        true,
      );
    }
    // fireflies at night around the village
    if (night > 0.4 && Math.random() < night * 0.6) {
      const a = Math.random() * Math.PI * 2;
      const r = 6 + Math.random() * 32;
      const x = PLAZA.x + Math.cos(a) * r;
      const z = PLAZA.z + Math.sin(a) * r;
      this.fx.spawn(
        {
          pos: { x, y: this.vox.heightAt(x, z) + 0.5 + Math.random() * 2, z },
          vel: { x: (Math.random() - 0.5) * 0.5, y: (Math.random() - 0.5) * 0.3, z: (Math.random() - 0.5) * 0.5 },
          color: 0xd8ff6a,
          size: 0.1,
          life: 3 + Math.random() * 2,
          tile: 0,
        },
        true,
      );
    }
  }

  // ---------------------------------------------------------------- picking
  private setPointer(e: PointerEvent): void {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
  }

  private pick(): string | null {
    this.raycaster.setFromCamera(this.pointer, this.rig.camera);
    const boxes: THREE.Object3D[] = [];
    for (const c of this.chars.values()) if (!c.isRemoving) boxes.push(c.hitBox);
    const hit = this.raycaster.intersectObjects(boxes, false)[0];
    return hit ? ((hit.object.userData.agentId as string) ?? null) : null;
  }

  private updateHover(): void {
    const id = this.pointerInside ? this.pick() : null;
    if (id === this.hoveredId) return;
    if (this.hoveredId) this.chars.get(this.hoveredId)?.setHovered(false);
    this.hoveredId = id;
    if (id) this.chars.get(id)?.setHovered(true);
    this.renderer.domElement.style.cursor = id ? 'pointer' : '';
    this.onHover(id);
  }

  private onPointerDown = (e: PointerEvent): void => {
    this.downAt = { x: e.clientX, y: e.clientY, t: performance.now() };
  };

  private onPointerUp = (e: PointerEvent): void => {
    const d = this.downAt;
    this.downAt = null;
    if (!d || e.button !== 0) return;
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6 || performance.now() - d.t > 600) return;
    this.setPointer(e);
    this.onSelect(this.pick());
  };

  private onPointerMove = (e: PointerEvent): void => {
    this.setPointer(e);
    this.pointerInside = true;
    this.pointerDirty = true;
  };

  private onPointerLeave = (): void => {
    this.pointerInside = false;
    this.pointerDirty = true;
  };
}
