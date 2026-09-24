// Sky dome, sun/moon squares, stars, blocky drifting clouds and the day/night lighting rig.
import * as THREE from 'three';
import { moonCanvas, pixelTexture, sunCanvas } from './textures';
import { Simplex2, clamp, smoothstep } from './noise';

interface SkyKey {
  e: number; // sun elevation (sin)
  top: THREE.Color;
  horizon: THREE.Color;
  sun: THREE.Color;
  sunI: number;
  hemiSky: THREE.Color;
  hemiGround: THREE.Color;
  hemiI: number;
}

const C = (h: number): THREE.Color => new THREE.Color(h);
const KEYS: SkyKey[] = [
  { e: -1, top: C(0x060a1e), horizon: C(0x1a2750), sun: C(0x9ab4ff), sunI: 0.9, hemiSky: C(0x6a7cc8), hemiGround: C(0x2a2840), hemiI: 1.25 },
  { e: -0.18, top: C(0x0c1434), horizon: C(0x2a3264), sun: C(0x9ab4ff), sunI: 0.85, hemiSky: C(0x6a7cc0), hemiGround: C(0x2a2638), hemiI: 1.2 },
  { e: -0.02, top: C(0x2b3d78), horizon: C(0xe88a5a), sun: C(0xff9a5a), sunI: 0.35, hemiSky: C(0x8a7aa8), hemiGround: C(0x3a2e2a), hemiI: 0.8 },
  { e: 0.12, top: C(0x4a74c2), horizon: C(0xffc08a), sun: C(0xffc48a), sunI: 1.6, hemiSky: C(0xb8c8e8), hemiGround: C(0x5a4a3a), hemiI: 1.0 },
  { e: 0.35, top: C(0x3f82e6), horizon: C(0xa8d4ff), sun: C(0xfff0d8), sunI: 2.6, hemiSky: C(0xcfe4ff), hemiGround: C(0x6a5a44), hemiI: 1.15 },
  { e: 1, top: C(0x3a7de6), horizon: C(0xa2d0ff), sun: C(0xfff6e8), sunI: 2.9, hemiSky: C(0xd8ecff), hemiGround: C(0x6a5a44), hemiI: 1.2 },
];

const SKY_VERT = /* glsl */ `
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  gl_Position = p.xyww;
}`;
const SKY_FRAG = /* glsl */ `
uniform vec3 uTop;
uniform vec3 uHorizon;
uniform vec3 uBottom;
uniform vec3 uSunDir;
uniform vec3 uSunColor;
uniform float uSunGlow;
varying vec3 vDir;
void main() {
  vec3 d = normalize(vDir);
  float h = d.y;
  vec3 col = h > 0.0 ? mix(uHorizon, uTop, pow(smoothstep(0.0, 0.55, h), 0.8)) : mix(uHorizon, uBottom, smoothstep(0.0, 0.12, -h));
  float s = max(0.0, dot(d, normalize(uSunDir)));
  col += uSunColor * (pow(s, 12.0) * 0.35 + pow(s, 3.0) * 0.12) * uSunGlow;
  gl_FragColor = vec4(col, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

export class Sky {
  readonly group = new THREE.Group();
  readonly sun: THREE.DirectionalLight;
  readonly hemi: THREE.HemisphereLight;
  readonly fog: THREE.Fog;
  private dome: THREE.Mesh;
  private domeMat: THREE.ShaderMaterial;
  private sunMesh: THREE.Mesh;
  private moonMesh: THREE.Mesh;
  private stars: THREE.Points;
  private starMat: THREE.PointsMaterial;
  private clouds: THREE.Group;
  private cloudMat: THREE.MeshLambertMaterial;
  private cloudSpan = 384;
  /** 0 = full day, 1 = full night */
  night = 0;
  /** normalized time of day 0..1 (0.5 = noon) */
  time = 0.45;
  private target = 0.45;
  mode: 'auto' | 'day' | 'night' = 'auto';
  readonly sunDir = new THREE.Vector3();

  constructor() {
    this.domeMat = new THREE.ShaderMaterial({
      uniforms: {
        uTop: { value: new THREE.Color() },
        uHorizon: { value: new THREE.Color() },
        uBottom: { value: new THREE.Color(0x1d3f6e) },
        uSunDir: { value: new THREE.Vector3(0, 1, 0) },
        uSunColor: { value: new THREE.Color(0xffd8a0) },
        uSunGlow: { value: 1 },
      },
      vertexShader: SKY_VERT,
      fragmentShader: SKY_FRAG,
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
    });
    this.dome = new THREE.Mesh(new THREE.SphereGeometry(500, 32, 16), this.domeMat);
    this.dome.renderOrder = -10;
    this.dome.frustumCulled = false;
    this.group.add(this.dome);

    const sq = new THREE.PlaneGeometry(1, 1);
    const sunMat = new THREE.MeshBasicMaterial({ map: pixelTexture(sunCanvas()), fog: false, depthWrite: false, transparent: true, color: new THREE.Color(1.6, 1.5, 1.3) });
    this.sunMesh = new THREE.Mesh(sq, sunMat);
    this.sunMesh.scale.setScalar(42);
    const moonMat = new THREE.MeshBasicMaterial({ map: pixelTexture(moonCanvas()), fog: false, depthWrite: false, transparent: true });
    this.moonMesh = new THREE.Mesh(sq, moonMat);
    this.moonMesh.scale.setScalar(30);
    this.sunMesh.renderOrder = this.moonMesh.renderOrder = -9;
    this.group.add(this.sunMesh, this.moonMesh);

    // stars
    const n = 900;
    const pos = new Float32Array(n * 3);
    let seed = 7;
    const r = (): number => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };
    for (let i = 0; i < n; i++) {
      const u = r() * 0.95 + 0.05;
      const a = r() * Math.PI * 2;
      const s = Math.sqrt(1 - u * u);
      pos.set([Math.cos(a) * s * 420, u * 420, Math.sin(a) * s * 420], i * 3);
    }
    const sg = new THREE.BufferGeometry();
    sg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.starMat = new THREE.PointsMaterial({ color: 0xffffff, size: 2, sizeAttenuation: false, transparent: true, opacity: 0, fog: false, depthWrite: false });
    this.stars = new THREE.Points(sg, this.starMat);
    this.stars.renderOrder = -8;
    this.group.add(this.stars);

    // clouds
    this.cloudMat = new THREE.MeshLambertMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, emissive: 0x777777, depthWrite: false });
    this.clouds = new THREE.Group();
    const cg = cloudGeometry(this.cloudSpan);
    for (const ox of [-1, 0, 1]) {
      const m = new THREE.Mesh(cg, this.cloudMat);
      m.position.set(ox * this.cloudSpan, 88, -this.cloudSpan / 2);
      m.renderOrder = 2;
      this.clouds.add(m);
    }
    this.group.add(this.clouds);

    // lights
    this.sun = new THREE.DirectionalLight(0xffffff, 2.5);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    const sc = this.sun.shadow.camera;
    sc.left = -60;
    sc.right = 60;
    sc.top = 60;
    sc.bottom = -60;
    sc.near = 1;
    sc.far = 260;
    this.sun.shadow.bias = -0.0004;
    this.sun.shadow.normalBias = 0.04;
    this.sun.shadow.radius = 3;
    this.hemi = new THREE.HemisphereLight(0xcfe4ff, 0x6a5a44, 1.1);
    this.fog = new THREE.Fog(0xbfe2ff, 100, 290);
  }

  setMode(mode: 'auto' | 'day' | 'night'): void {
    this.mode = mode;
  }

  private static clockTime(): number {
    const d = new Date();
    return (d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600) / 24;
  }

  /** immediately jump to the current target time (on startup) */
  snap(): void {
    this.target = this.targetTime();
    this.time = this.target;
  }

  private targetTime(): number {
    if (this.mode === 'day') return 0.44;
    if (this.mode === 'night') return 0.96;
    return Sky.clockTime();
  }

  update(dt: number, cameraPos: THREE.Vector3): void {
    this.target = this.targetTime();
    let diff = this.target - this.time;
    if (diff > 0.5) diff -= 1;
    if (diff < -0.5) diff += 1;
    this.time = (this.time + diff * Math.min(1, dt * 1.2) + 1) % 1;

    // sun path: rises east (+x), sets west; tilted toward the south so shadows fall north-ish
    const ang = (this.time - 0.25) * Math.PI * 2;
    const e = Math.sin(ang);
    this.sunDir.set(Math.cos(ang) * 0.85, e, 0.42).normalize();
    // interpolate keyframes by elevation
    let a = KEYS[0];
    let b = KEYS[KEYS.length - 1];
    for (let i = 0; i < KEYS.length - 1; i++)
      if (e >= KEYS[i].e && e <= KEYS[i + 1].e) {
        a = KEYS[i];
        b = KEYS[i + 1];
        break;
      }
    const t = clamp((e - a.e) / (b.e - a.e || 1), 0, 1);
    const top = a.top.clone().lerp(b.top, t);
    const hor = a.horizon.clone().lerp(b.horizon, t);
    this.domeMat.uniforms.uTop.value.copy(top);
    this.domeMat.uniforms.uHorizon.value.copy(hor);
    this.domeMat.uniforms.uBottom.value.copy(hor).multiplyScalar(0.55);
    this.domeMat.uniforms.uSunDir.value.copy(this.sunDir);
    this.domeMat.uniforms.uSunGlow.value = smoothstep(-0.25, 0.05, e);
    this.domeMat.uniforms.uSunColor.value.copy(a.sun).lerp(b.sun, t);
    this.night = 1 - smoothstep(-0.2, 0.08, e);

    // light: sun by day, moon by night (same light, shadows keep working)
    const moon = e < -0.04;
    const lightDir = moon ? this.sunDir.clone().negate() : this.sunDir.clone();
    if (lightDir.y < 0.18) lightDir.y = 0.18; // keep light from grazing
    lightDir.normalize();
    this.sun.color.copy(a.sun).lerp(b.sun, t);
    this.sun.intensity = a.sunI + (b.sunI - a.sunI) * t;
    const fc = this.sun.position;
    fc.copy(lightDir).multiplyScalar(120).add(this.sun.target.position);
    this.hemi.color.copy(a.hemiSky).lerp(b.hemiSky, t);
    this.hemi.groundColor.copy(a.hemiGround).lerp(b.hemiGround, t);
    this.hemi.intensity = a.hemiI + (b.hemiI - a.hemiI) * t;
    this.fog.color.copy(hor).lerp(top, 0.25);

    // celestial bodies follow the camera
    this.group.position.copy(cameraPos);
    this.clouds.position.set(-cameraPos.x, -cameraPos.y, -cameraPos.z); // clouds are world-anchored
    this.sunMesh.position.copy(this.sunDir).multiplyScalar(400);
    this.sunMesh.lookAt(0, 0, 0);
    this.moonMesh.position.copy(this.sunDir).multiplyScalar(-400);
    this.moonMesh.lookAt(0, 0, 0);
    this.sunMesh.visible = e > -0.15;
    this.moonMesh.visible = e < 0.15;
    this.starMat.opacity = this.night * 0.9;
    this.stars.visible = this.night > 0.02;
    this.stars.rotation.y += dt * 0.004;

    // clouds drift east
    for (const m of this.clouds.children) {
      m.position.x += dt * 1.2;
      if (m.position.x > this.cloudSpan * 1.5) m.position.x -= this.cloudSpan * 3;
    }
    // fade clouds out when the camera climbs toward them
    this.cloudMat.opacity = 0.82 * (1 - smoothstep(58, 80, cameraPos.y));
    this.clouds.visible = this.cloudMat.opacity > 0.01;
    const cloudTint = 1 - this.night * 0.75;
    this.cloudMat.color.setRGB(cloudTint, cloudTint, Math.min(1, cloudTint * 1.08));
    this.cloudMat.emissive.copy(hor).multiplyScalar(0.35 * (1 - this.night * 0.6));
  }

  dispose(): void {
    this.group.traverse((o) => {
      const m = o as THREE.Mesh;
      if ((m as THREE.Mesh).isMesh || (o as THREE.Points).isPoints) {
        m.geometry.dispose();
        const mat = m.material as THREE.Material & { map?: THREE.Texture | null };
        mat.map?.dispose();
        mat.dispose();
      }
    });
  }
}

/** Flat blocky cloud layer (MC-like), merged boxes from a noise mask. */
function cloudGeometry(span: number): THREE.BufferGeometry {
  const cell = 8;
  const n = span / cell;
  const noise = new Simplex2(2024);
  const mask = (i: number, j: number): boolean => {
    const ii = ((i % n) + n) % n;
    const jj = ((j % n) + n) % n;
    // tileable: sample a torus
    const a = (ii / n) * Math.PI * 2;
    const b = (jj / n) * Math.PI * 2;
    const v = noise.noise(Math.cos(a) * 2.2 + 10, Math.sin(a) * 2.2) * 0.6 + noise.noise(Math.cos(b) * 2.2, Math.sin(b) * 2.2 + 20) * 0.6 + noise.noise(ii * 0.35, jj * 0.35) * 0.5;
    return v > 0.35;
  };
  const pos: number[] = [];
  const nor: number[] = [];
  const idx: number[] = [];
  const h = 3;
  const quad = (p: number[][], nn: number[]): void => {
    const base = pos.length / 3;
    for (const v of p) {
      pos.push(v[0], v[1], v[2]);
      nor.push(nn[0], nn[1], nn[2]);
    }
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  };
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) {
      if (!mask(i, j)) continue;
      const x0 = i * cell;
      const z0 = j * cell;
      const x1 = x0 + cell;
      const z1 = z0 + cell;
      quad([[x0, h, z1], [x1, h, z1], [x1, h, z0], [x0, h, z0]], [0, 1, 0]);
      quad([[x0, 0, z0], [x1, 0, z0], [x1, 0, z1], [x0, 0, z1]], [0, -1, 0]);
      if (!mask(i + 1, j)) quad([[x1, 0, z1], [x1, 0, z0], [x1, h, z0], [x1, h, z1]], [1, 0, 0]);
      if (!mask(i - 1, j)) quad([[x0, 0, z0], [x0, 0, z1], [x0, h, z1], [x0, h, z0]], [-1, 0, 0]);
      if (!mask(i, j + 1)) quad([[x0, 0, z1], [x1, 0, z1], [x1, h, z1], [x0, h, z1]], [0, 0, 1]);
      if (!mask(i, j - 1)) quad([[x1, 0, z0], [x0, 0, z0], [x0, h, z0], [x1, h, z0]], [0, 0, -1]);
    }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setIndex(idx);
  return g;
}
