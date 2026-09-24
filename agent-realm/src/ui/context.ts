import type { Store } from '../store';

export type Place = 'overview' | 'council' | 'village';
export type TimeMode = 'auto' | 'day' | 'night';

/** What UI components can ask the app to do. Implemented in main.ts, which owns the World. */
export interface Ctx {
  store: Store;
  select(id: string | null, opts?: { follow?: boolean }): void;
  follow(id: string | null): void;
  goTo(place: Place): void;
  openChamber(missionId?: string, taskId?: string): void;
  closeChamber(): void;
  setTime(mode: TimeMode): void;
  timeMode: TimeMode;
  place: Place;
  summon(goal: string): void;
}
