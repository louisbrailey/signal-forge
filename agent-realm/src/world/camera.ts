// Perspective camera + OrbitControls with smooth fly-to transitions, follow mode and idle auto-orbit.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { HALF } from './layout';

interface Tween {
  fromPos: THREE.Vector3;
  fromTarget: THREE.Vector3;
  toPos: THREE.Vector3;
  toTarget: THREE.Vector3;
  t: number;
  dur: number;
}

function ease(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

export class CameraRig {
  readonly camera: THREE.PerspectiveCamera;
  readonly controls: OrbitControls;
  private tween: Tween | null = null;
  private followFn: (() => THREE.Vector3 | null) | null = null;
  private lastFollow = new THREE.Vector3();
  private followBlend = 0;
  private idleTime = 0;
  private autoOrbit = false;
  idleDelay = 60;

  constructor(dom: HTMLElement) {
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.3, 1400);
    this.controls = new OrbitControls(this.camera, dom);
    const c = this.controls;
    c.enableDamping = true;
    c.dampingFactor = 0.08;
    c.minDistance = 5;
    c.maxDistance = 160;
    c.maxPolarAngle = Math.PI * 0.44;
    c.minPolarAngle = 0.12;
    c.screenSpacePanning = false;
    c.zoomSpeed = 0.9;
    c.rotateSpeed = 0.6;
    c.panSpeed = 0.8;
    c.autoRotateSpeed = 0.35;
    c.addEventListener('start', () => this.onInput());
    dom.addEventListener('wheel', () => this.onInput(), { passive: true });
  }

  private onInput(): void {
    this.idleTime = 0;
    if (this.autoOrbit) {
      this.autoOrbit = false;
      this.controls.autoRotate = false;
    }
    // manual input cancels an in-flight tween (but keeps following)
    this.tween = null;
  }

  set(position: THREE.Vector3Like, target: THREE.Vector3Like): void {
    this.camera.position.set(position.x, position.y, position.z);
    this.controls.target.set(target.x, target.y, target.z);
    this.controls.update();
  }

  flyTo(target: THREE.Vector3, position: THREE.Vector3, dur = 1.6): void {
    this.tween = {
      fromPos: this.camera.position.clone(),
      fromTarget: this.controls.target.clone(),
      toPos: position.clone(),
      toTarget: target.clone(),
      t: 0,
      dur,
    };
    this.idleTime = 0;
  }

  /** follow a moving point; null stops following */
  follow(fn: (() => THREE.Vector3 | null) | null): void {
    this.followFn = fn;
    this.followBlend = 0;
    const p = fn?.();
    if (p) {
      this.lastFollow.copy(p);
      // fly to a pleasant offset around the agent, keeping current viewing direction
      const dir = this.camera.position.clone().sub(this.controls.target).normalize();
      if (dir.y < 0.35) dir.y = 0.35;
      dir.normalize();
      this.flyTo(p, p.clone().addScaledVector(dir, 11), 1.4);
    }
  }

  get following(): boolean {
    return this.followFn !== null;
  }

  update(dt: number): void {
    this.idleTime += dt;
    if (!this.autoOrbit && this.idleTime > this.idleDelay && !this.tween) {
      this.autoOrbit = true;
      this.controls.autoRotate = true;
    }
    if (this.tween) {
      const tw = this.tween;
      tw.t = Math.min(1, tw.t + dt / tw.dur);
      const k = ease(tw.t);
      // while following, the destination tracks the moving target
      if (this.followFn) {
        const p = this.followFn();
        if (p) {
          const delta = p.clone().sub(tw.toTarget);
          tw.toTarget.add(delta);
          tw.toPos.add(delta);
          this.lastFollow.copy(p);
        }
      }
      this.controls.target.lerpVectors(tw.fromTarget, tw.toTarget, k);
      // arc the camera slightly upward mid-flight for a nicer move
      this.camera.position.lerpVectors(tw.fromPos, tw.toPos, k);
      this.camera.position.y += Math.sin(k * Math.PI) * Math.min(12, tw.fromPos.distanceTo(tw.toPos) * 0.12);
      if (tw.t >= 1) this.tween = null;
    } else if (this.followFn) {
      const p = this.followFn();
      if (p) {
        const delta = p.clone().sub(this.lastFollow);
        this.followBlend = Math.min(1, this.followBlend + dt * 2);
        this.controls.target.add(delta);
        this.camera.position.add(delta);
        this.lastFollow.copy(p);
      }
    }
    // keep the target on the island
    const t = this.controls.target;
    t.x = Math.max(-HALF - 10, Math.min(HALF + 10, t.x));
    t.z = Math.max(-HALF - 10, Math.min(HALF + 10, t.z));
    t.y = Math.max(4, Math.min(40, t.y));
    this.controls.update(dt);
    if (this.camera.position.y < 9.5) this.camera.position.y = 9.5;
  }

  resize(w: number, h: number): void {
    this.camera.aspect = w / Math.max(1, h);
    this.camera.updateProjectionMatrix();
  }

  dispose(): void {
    this.controls.dispose();
  }
}
