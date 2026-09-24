// World layout constants and deterministic seat / plot allocation.

export const WORLD = 96; // blocks per side
export const HALF = WORLD / 2;
export const HEIGHT = 44;
export const SEA = 8; // top of water is at SEA + 0.85
export const VILLAGE_Y = 11; // surface block y in the village (stand at +1)
export const HALL_Y = 17; // surface block y of the council plateau

export const HALL = { x: 0, z: -24, plateau: 12 } as const;
export const PLAZA = { x: 0, z: 6, r: 5 } as const;
export const TABLE_R = 2; // radius (blocks) of the round council table
export const SEAT_R = 4.1;

export interface Seat {
  x: number;
  z: number;
  facing: number; // yaw (radians) — character +z faces this direction
}

/** yaw such that a model whose front is +z faces (dx, dz) */
export function yawTo(dx: number, dz: number): number {
  return Math.atan2(dx, dz);
}

/** Council seats around the round table: far side first so the camera sees faces. */
export function councilSeats(n: number): Seat[] {
  const seats: Seat[] = [];
  const count = Math.max(1, n);
  const inner = Math.min(count, 7);
  const step = (Math.PI * 2) / Math.max(7, inner);
  for (let i = 0; i < count; i++) {
    const ring = i < inner ? 0 : 1;
    const k = ring === 0 ? i : i - inner;
    const kN = ring === 0 ? inner : count - inner;
    const st = ring === 0 ? step : (Math.PI * 2) / Math.max(kN, 8);
    const theta = -Math.PI / 2 + (k - (kN - 1) / 2) * st; // -π/2 = north (-z)
    const r = ring === 0 ? SEAT_R : SEAT_R + 2.2;
    const x = HALL.x + Math.cos(theta) * r;
    const z = HALL.z + Math.sin(theta) * r;
    seats.push({ x, z, facing: yawTo(HALL.x - x, HALL.z - z) });
  }
  return seats;
}

export interface PlotSlot {
  index: number;
  cx: number; // centre block x
  cz: number; // centre block z
}

export const PLOT_HALF = 3; // 7×7 plots

/**
 * Village grid: rows of 7×7 plots, each row's entrances (south side) open onto an east-west street.
 * A central avenue runs south from the plaza. 24 plots, filled nearest-to-plaza first.
 */
export const PLOT_ROWS: { cz: number; xs: number[]; street: number }[] = [
  { cz: -1, xs: [9, 17, 25], street: 3 },
  { cz: 9, xs: [9, 17, 25, 33], street: 13 },
  { cz: 19, xs: [5, 13, 21, 29], street: 23 },
  { cz: 29, xs: [5, 13], street: 33 },
];
export const AVENUE = { x0: -1, x1: 1, z0: PLAZA.z + PLAZA.r, z1: 34 };

function computePlots(): PlotSlot[] {
  const out: PlotSlot[] = [];
  for (const row of PLOT_ROWS) for (const x of row.xs) for (const sx of [-x, x]) out.push({ index: 0, cx: sx, cz: row.cz });
  out.sort((p, q) => {
    const dp = Math.hypot(p.cx - PLAZA.x, p.cz - (PLAZA.z + 4));
    const dq = Math.hypot(q.cx - PLAZA.x, q.cz - (PLAZA.z + 4));
    return dp - dq || p.cx - q.cx;
  });
  out.forEach((p, i) => (p.index = i));
  return out;
}

export const PLOTS: PlotSlot[] = computePlots();

/** Positions of named places for the camera. */
export const PLACES = {
  overview: { target: [0, 10, -2] as const, offset: [46, 44, 62] as const },
  council: { target: [HALL.x, HALL_Y + 1.5, HALL.z] as const, offset: [5, 18, 19] as const },
  village: { target: [PLAZA.x, VILLAGE_Y + 2, PLAZA.z + 11] as const, offset: [0, 30, 34] as const },
};
