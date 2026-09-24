import type { Mission } from '../shared/protocol';
import { Store } from './store';
import type { Ctx, Place, TimeMode } from './ui/context';
import { Hud } from './ui/hud';
import { esc, modelLabel } from './ui/util';
import { World } from './world/World';

const store = new Store();
const world = new World(document.getElementById('world')!);
const TIME_CYCLE: TimeMode[] = ['auto', 'day', 'night'];

const ctx: Ctx = {
  store,
  place: 'overview',
  timeMode: loadPref<TimeMode>('time', 'auto'),
  select(id, opts) {
    store.selectedId = id;
    world.setSelected(id);
    if (opts?.follow && id) ctx.follow(id);
    if (!id) ctx.follow(null);
    store.changed();
  },
  follow(id) {
    store.followId = id;
    world.focusAgent(id);
    store.changed();
  },
  goTo(place: Place) {
    ctx.place = place;
    store.followId = null;
    world.focusPlace(place);
    store.changed();
  },
  openChamber(missionId, taskId) { hud.chamber.show(missionId, taskId); },
  closeChamber() { hud.chamber.hide(); },
  setTime(mode) {
    ctx.timeMode = mode;
    world.setTimeMode(mode);
    savePref('time', mode);
    store.changed();
  },
  summon(goal) {
    if (!store.send({ type: 'summon_council', goal })) {
      hud.toast('Not connected to the realm server — is it running?', 'error');
      return;
    }
    hud.toast('The council convenes…', 'success');
    ctx.goTo('council');
  },
};

const hud = new Hud(document.getElementById('hud')!, ctx);
world.setTimeMode(ctx.timeMode);

// ---- world ↔ store wiring
world.onSelect = (id) => ctx.select(id, { follow: false });
world.onHover = (id) => {
  document.body.style.cursor = id ? 'pointer' : '';
  hovered = id;
};
let hovered: string | null = null;
let lastMissionKey = '';

store.subscribe(() => {
  world.setAgents([...store.agents.values()]);
  const m = activeMission();
  const key = m ? `${m.id}:${m.status}` : '';
  if (key !== lastMissionKey) { lastMissionKey = key; world.setMission(m ?? null); }
  hud.render();
});

store.onServer.add((msg) => {
  switch (msg.type) {
    case 'activity': world.onActivity(msg.activity); break;
    case 'delegate': world.delegate(msg.fromId, msg.toId); break;
    case 'deliver': world.deliver(msg.fromId, msg.toId); break;
    case 'snapshot':
      if (!loadPref('welcomed', '')) { savePref('welcomed', '1'); setTimeout(() => hud.showWelcome(), 600); }
      break;
  }
});

function activeMission(): Mission | undefined {
  return [...store.missions.values()]
    .filter((m) => !['complete', 'failed', 'cancelled'].includes(m.status))
    .sort((a, b) => b.createdAt - a.createdAt)[0];
}

// Hover tooltip that tracks the villager on screen.
function tick(): void {
  const id = hovered ?? hud.rosterHover;
  const a = id ? store.agents.get(id) : undefined;
  const p = a ? world.getScreenPosition(a.id) : null;
  if (a && p?.visible && hovered) {
    hud.showTip(`<b>${esc(a.name)}</b> <span class="faint">${esc(modelLabel(a.model) || a.title)}</span>${a.currentAction ? `<br/><span class="mono" style="font-size:11.5px">${esc(a.currentAction)}</span>` : ''}`, p.x, p.y);
  } else hud.showTip(null);
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// Relative times ("12s ago") stay fresh.
setInterval(() => store.changed(), 1000);

// ---- keyboard
window.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const tag = (e.target as HTMLElement)?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  const k = e.key;
  if (k === 'Escape') {
    if (hud.overlayOpen) hud.closeOverlay();
    else if (hud.chamber.open) ctx.closeChamber();
    else if (store.selectedId) ctx.select(null);
    return;
  }
  if (hud.overlayOpen || hud.chamber.open) {
    if (k.toLowerCase() === 'm' && hud.chamber.open) ctx.closeChamber();
    return;
  }
  if (k === 't' || k === 'T' || k === '/') { e.preventDefault(); hud.focusCommand(); return; }
  if (/^[1-9]$/.test(k)) { const id = hud.hotbarAgent(Number(k) - 1); if (id) ctx.select(id, { follow: true }); return; }
  switch (k.toLowerCase()) {
    case 'o': ctx.goTo('overview'); break;
    case 'c': ctx.goTo('council'); break;
    case 'v': ctx.goTo('village'); break;
    case 'm': ctx.openChamber(); break;
    case 'f': if (store.selectedId) ctx.follow(store.followId ? null : store.selectedId); break;
    case 'n': ctx.setTime(TIME_CYCLE[(TIME_CYCLE.indexOf(ctx.timeMode) + 1) % TIME_CYCLE.length]); break;
    case '?': hud.showHelp(); break;
    case 'tab': e.preventDefault(); hud.toggleRoster(); break;
  }
});

store.connect();

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register('/sw.js').catch(() => undefined);
}

function loadPref<T extends string>(key: string, fallback: T): T {
  try { return (localStorage.getItem(`realm.${key}`) as T) || fallback; } catch { return fallback; }
}
function savePref(key: string, v: string): void {
  try { localStorage.setItem(`realm.${key}`, v); } catch { /* private mode */ }
}
