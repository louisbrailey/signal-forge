import type { Agent } from '../../shared/protocol';
import type { Ctx, Place, TimeMode } from './context';
import { Chamber } from './chamber';
import { Inspector } from './inspector';
import { SOURCE_LABEL, ago, esc, h, headImg, modelLabel, statusDot } from './util';

type Filter = 'all' | 'active' | 'live' | 'council';

const EXAMPLES = [
  'Design a REST API for my hydroponic garden sensors',
  'Plan and write a launch checklist for my trading dashboard',
  'Draft a test strategy for signal-forge’s risk engine',
  'Write onboarding docs for a new contributor',
];

/** All HTML overlay chrome around the 3D world. */
export class Hud {
  private top = h('header', 'topbar panel');
  private roster = h('aside', 'roster panel');
  private rosterList = h('div', 'scroll');
  private hotbar = h('nav', 'hotbar panel');
  private chat = h('div', 'chat');
  private feed = h('div', 'feed');
  private quest = h('section', 'quest panel');
  private toasts = h('div', 'toasts');
  private tip = h('div', 'hover-tip panel hidden');
  private overlay = h('div', 'sheet-wrap hidden');
  readonly inspector: Inspector;
  readonly chamber: Chamber;
  private filter: Filter = 'all';
  private query = '';
  private questOpen = true;
  private shownFeed = 0;
  private hotbarIds: string[] = [];

  constructor(root: HTMLElement, private ctx: Ctx) {
    this.inspector = new Inspector(ctx);
    this.chamber = new Chamber(ctx);
    this.buildTop();
    this.buildRoster();
    this.buildChat();
    root.append(this.top, this.roster, this.inspector.el, this.hotbar, this.chat, this.quest, this.toasts, this.tip, this.chamber.el, this.overlay);

    this.hotbar.addEventListener('click', (e) => {
      const s = (e.target as HTMLElement).closest<HTMLElement>('[data-id]');
      if (s) ctx.select(s.dataset.id!, { follow: true });
    });
    this.quest.addEventListener('click', (e) => {
      const t = (e.target as HTMLElement).closest<HTMLElement>('[data-act]');
      if (t?.dataset.act === 'toggle') { this.questOpen = !this.questOpen; this.render(); }
      else if (t?.dataset.act === 'open') ctx.openChamber(ctx.store.missionId ?? undefined);
      else if (t?.dataset.act === 'focus') ctx.goTo('council');
    });
    this.overlay.addEventListener('mousedown', (e) => { if (e.target === this.overlay) this.closeOverlay(); });
    this.overlay.addEventListener('click', (e) => {
      const t = (e.target as HTMLElement).closest<HTMLElement>('[data-act]');
      if (t?.dataset.act === 'close') this.closeOverlay();
      if (t?.dataset.act === 'example') { this.closeOverlay(); this.fillCommand(t.dataset.text ?? ''); }
    });
    ctx.store.onServer.add((m) => { if (m.type === 'toast') this.toast(m.text, m.level); });
  }

  // ---------------------------------------------------------------- top bar
  private buildTop(): void {
    this.top.innerHTML = `
      <div class="brand"><img class="logo" src="/icon.svg" alt=""/><div>AGENT REALM<br/><small id="tb-host">connecting…</small></div></div>
      <div class="stats" id="tb-stats"></div>
      <div class="spacer"></div>
      <div id="tb-badges" style="display:flex;gap:6px"></div>
      <div class="seg" id="tb-place" role="group" aria-label="Camera">
        <button data-place="overview" title="Overview (O)">Overview</button><button data-place="council" title="Council hall (C)">Council</button><button data-place="village" title="Village (V)">Village</button>
      </div>
      <div class="seg" id="tb-time" role="group" aria-label="Time of day">
        <button data-time="auto" title="Follows your clock">☼☾</button><button data-time="day" title="Always day">☼</button><button data-time="night" title="Always night (N)">☾</button>
      </div>
      <button class="btn gold" data-act="chamber" title="Council chamber (M)">♛ Chamber</button>
      <button class="btn ghost small" data-act="help" title="Help (?)">?</button>
      <div class="conn" id="tb-conn"></div>`;
    this.top.addEventListener('click', (e) => {
      const t = e.target as HTMLElement;
      const place = t.closest<HTMLElement>('[data-place]')?.dataset.place as Place | undefined;
      const time = t.closest<HTMLElement>('[data-time]')?.dataset.time as TimeMode | undefined;
      const act = t.closest<HTMLElement>('[data-act]')?.dataset.act;
      if (place) this.ctx.goTo(place);
      if (time) this.ctx.setTime(time);
      if (act === 'chamber') this.ctx.openChamber();
      if (act === 'help') this.showHelp();
      if (act === 'demo') this.ctx.store.send({ type: 'set_demo', enabled: !this.ctx.store.info?.demoPopulation });
      this.render();
    });
  }

  private renderTop(): void {
    const { store } = this.ctx;
    const agents = [...store.agents.values()].filter((a) => a.status !== 'offline');
    const detected = agents.filter((a) => a.live && a.source !== 'api');
    const busy = agents.filter((a) => a.status === 'working' || a.status === 'thinking');
    const m = store.missionId ? store.missions.get(store.missionId) : undefined;
    const tasks = m ? store.missionTasks(m) : [];
    const done = tasks.filter((t) => t.status === 'done').length;
    this.top.querySelector('#tb-host')!.textContent = store.info ? `${store.info.hostname} · ${platformName(store.info.platform)}` : 'connecting…';
    this.top.querySelector('#tb-stats')!.innerHTML = `
      <div class="stat" title="Real agents found on this machine"><b>${detected.length}</b><span>Detected</span></div>
      <div class="stat" title="Working or thinking right now"><i class="dot s-working ${busy.length ? 'pulse' : ''}"></i><b>${busy.length}</b><span>Busy</span></div>
      <div class="stat"><b>${agents.filter((a) => a.role === 'council').length}</b><span>Council</span></div>
      <div class="stat" title="Current mission quests"><b>${tasks.length ? `${done}/${tasks.length}` : '—'}</b><span>Quests</span></div>`;
    const info = store.info;
    this.top.querySelector('#tb-badges')!.innerHTML = info ? `
      ${info.apiKeyPresent ? '<span class="badge api" title="Council and workers run on the Claude API">API live</span>' : '<span class="badge sim" title="No ANTHROPIC_API_KEY — missions are simulated">Sim council</span>'}
      <button class="chip ${info.demoPopulation ? 'on' : ''}" data-act="demo" title="Show simulated citizens alongside real agents">${info.demoPopulation ? '◉' : '○'} Demo citizens</button>` : '';
    this.top.querySelectorAll<HTMLElement>('[data-place]').forEach((b) => b.classList.toggle('on', b.dataset.place === this.ctx.place));
    this.top.querySelectorAll<HTMLElement>('[data-time]').forEach((b) => b.classList.toggle('on', b.dataset.time === this.ctx.timeMode));
    const c = store.conn;
    this.top.querySelector('#tb-conn')!.innerHTML = `<i class="dot ${c === 'open' ? 's-working' : c === 'connecting' ? 's-waiting pulse' : 's-error'}"></i>${c === 'open' ? 'live' : c}`;
  }

  // ---------------------------------------------------------------- roster
  private buildRoster(): void {
    const head = h('div', 'panel-head', `<h2>Villagers</h2><span class="count" id="ro-count"></span><span class="grow"></span><button class="btn ghost small" data-act="collapse" title="Hide (Tab)">⟨</button>`);
    const filters = h('div', 'filters', `
      <input class="search" placeholder="Search name, model, project…" aria-label="Search villagers" />
      ${(['all', 'active', 'live', 'council'] as Filter[]).map((f) => `<button class="chip" data-filter="${f}">${{ all: 'All', active: 'Busy', live: 'Detected', council: '♛ Council' }[f]}</button>`).join('')}`);
    this.roster.append(head, filters, this.rosterList);
    this.rosterList.style.flex = '1';
    filters.querySelector('input')!.addEventListener('input', (e) => { this.query = (e.target as HTMLInputElement).value.toLowerCase(); this.render(); });
    filters.querySelector('input')!.addEventListener('keydown', (e) => e.stopPropagation());
    this.roster.addEventListener('click', (e) => {
      const t = e.target as HTMLElement;
      const f = t.closest<HTMLElement>('[data-filter]')?.dataset.filter as Filter | undefined;
      if (f) { this.filter = f; this.render(); return; }
      if (t.closest('[data-act="collapse"]')) { this.toggleRoster(); return; }
      const row = t.closest<HTMLElement>('.row');
      if (row) this.ctx.select(row.dataset.id!, { follow: true });
    });
    this.roster.addEventListener('mouseover', (e) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>('.row');
      if (row) this.rosterHover = row.dataset.id ?? null;
    });
  }

  rosterHover: string | null = null;

  toggleRoster(): void { this.roster.classList.toggle('collapsed'); }

  private renderRoster(): void {
    const { store } = this.ctx;
    let list = store.sortedAgents();
    const total = list.length;
    if (this.filter === 'active') list = list.filter((a) => a.status === 'working' || a.status === 'thinking');
    if (this.filter === 'live') list = list.filter((a) => a.live && a.source !== 'api');
    if (this.filter === 'council') list = list.filter((a) => a.role === 'council');
    if (this.query) list = list.filter((a) => `${a.name} ${a.title} ${a.model ?? ''} ${a.project ?? ''} ${SOURCE_LABEL[a.source]}`.toLowerCase().includes(this.query));
    this.roster.querySelector('#ro-count')!.textContent = String(total);
    this.roster.querySelectorAll<HTMLElement>('[data-filter]').forEach((b) => b.classList.toggle('on', b.dataset.filter === this.filter));

    const council = list.filter((a) => a.role === 'council');
    const workers = list.filter((a) => a.role === 'worker');
    const detectedCount = [...store.agents.values()].filter((a) => a.live && a.source !== 'api').length;
    const group = (label: string, xs: Agent[]) => xs.length ? `<div class="group-label">${label} · ${xs.length}</div>${xs.map((a) => this.row(a)).join('')}` : '';
    this.rosterList.innerHTML =
      group('♛ The Council', council) +
      group('⚒ Workforce', workers) +
      (!list.length ? `<div class="empty">No villagers match.</div>` : '') +
      (store.info && detectedCount === 0 && this.filter === 'all' && !this.query ? `<div class="empty"><b>No local agents detected yet.</b><br/>Start Claude Code, Codex, Gemini CLI, Aider or Ollama and they'll walk into the village within a few seconds.</div>` : '');
  }

  private row(a: Agent): string {
    const sel = this.ctx.store.selectedId === a.id;
    const sub = [modelLabel(a.model), a.project, !a.live ? 'demo' : ''].filter(Boolean).join(' · ') || a.title;
    return `<div class="row ${sel ? 'sel' : ''} ${a.status === 'offline' ? 'offline' : ''}" data-id="${a.id}" tabindex="0" role="button" aria-label="${esc(a.name)}">
      ${headImg(a.skin)}
      <div style="min-width:0">
        <div class="name">${statusDot(a.status)}<span>${esc(a.name)}</span></div>
        <div class="sub">${esc(SOURCE_LABEL[a.source])} · ${esc(sub)}</div>
        ${a.currentAction && a.status !== 'idle' ? `<div class="act">${esc(a.currentAction)}</div>` : ''}
      </div>
      <div class="meta"><span>${ago(a.lastActivityAt, this.ctx.store.now)}</span>${a.currentTaskId ? '<span title="Has a quest">📜</span>' : ''}</div>
    </div>`;
  }

  // ---------------------------------------------------------------- hotbar
  private renderHotbar(): void {
    const { store } = this.ctx;
    const picks = store.sortedAgents().filter((a) => a.status !== 'offline').slice(0, 9);
    this.hotbarIds = picks.map((a) => a.id);
    this.hotbar.innerHTML = Array.from({ length: 9 }, (_, i) => {
      const a = picks[i];
      if (!a) return `<div class="slot"><span class="num">${i + 1}</span></div>`;
      const t = a.currentTaskId ? store.tasks.get(a.currentTaskId) : undefined;
      return `<div class="slot ${a.role === 'council' ? 'council' : ''} ${store.selectedId === a.id ? 'sel' : ''}" data-id="${a.id}" title="${esc(a.name)} — ${esc(a.title)}">
        <span class="num">${i + 1}</span>${headImg(a.skin)}${statusDot(a.status)}
        ${t && t.status === 'in_progress' ? `<span class="bar"><i style="width:${Math.round(t.progress * 100)}%"></i></span>` : ''}</div>`;
    }).join('');
  }

  hotbarAgent(i: number): string | undefined { return this.hotbarIds[i]; }

  // ---------------------------------------------------------------- chat / command
  private buildChat(): void {
    const cmd = h('form', 'command panel', `
      <span class="prompt">♛ ›</span>
      <input name="goal" autocomplete="off" spellcheck="false" placeholder="Summon the council: describe a goal…" aria-label="Summon the council with a goal" maxlength="2000"/>
      <span class="kbd" title="Focus">T</span>
      <button class="btn gold small" type="submit">Summon</button>`);
    const input = cmd.querySelector('input')!;
    cmd.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v) { this.showExamples(); return; }
      this.ctx.summon(v);
      input.value = '';
      input.blur();
    });
    input.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') input.blur();
    });
    input.addEventListener('focus', () => this.chat.classList.add('expanded'));
    input.addEventListener('blur', () => setTimeout(() => this.chat.classList.remove('expanded'), 150));
    this.chat.append(this.feed, cmd);
  }

  focusCommand(): void { this.chat.querySelector('input')?.focus(); }

  fillCommand(text: string): void {
    const input = this.chat.querySelector('input')!;
    input.value = text;
    input.focus();
  }

  private renderFeed(): void {
    const { store } = this.ctx;
    const lines = store.feed.slice(-60);
    if (store.feed.length === this.shownFeed && lines.length) { this.ageFeed(); return; }
    this.shownFeed = store.feed.length;
    const color = { activity: 'var(--text)', council: 'var(--gold)', system: 'var(--text-2)', success: 'var(--emerald)', warn: 'var(--amber)', error: 'var(--redstone)' } as const;
    this.feed.innerHTML = lines.map((l) => {
      const a = l.agentId ? store.agents.get(l.agentId) : undefined;
      const who = a ? `<span class="who" style="color:${a.role === 'council' ? 'var(--gold)' : a.skin.shirt}">&lt;${esc(a.name)}&gt;</span> ` : '';
      return `<div class="line" data-ts="${l.ts}" style="color:${color[l.tone]}">${who}${esc(l.text)}</div>`;
    }).join('');
    this.feed.scrollTop = this.feed.scrollHeight;
    this.ageFeed();
  }

  private ageFeed(): void {
    const now = Date.now();
    this.feed.querySelectorAll<HTMLElement>('.line').forEach((el) => el.classList.toggle('old', now - Number(el.dataset.ts) > 12_000));
  }

  // ---------------------------------------------------------------- quest log
  private renderQuest(): void {
    const { store } = this.ctx;
    const m = store.missionId ? store.missions.get(store.missionId) : undefined;
    if (!m) {
      this.quest.innerHTML = `<div class="panel-head"><h2>📜 Quest log</h2></div>
        <div class="quest-body"><div class="muted">No active mission. Give the council a goal and watch it plan, delegate and review.</div>
        <button class="btn gold small" style="align-self:flex-start" data-act="open">Open chamber</button></div>`;
      return;
    }
    const tasks = store.missionTasks(m);
    const done = tasks.filter((t) => t.status === 'done').length;
    const order = ['convening', 'deliberating', 'planning', 'executing', 'reviewing', 'complete'];
    const idx = order.indexOf(m.status);
    const active = tasks.filter((t) => t.status === 'in_progress' || t.status === 'review').slice(0, 4);
    this.quest.innerHTML = `
      <div class="panel-head" data-act="toggle"><h2>📜 Quest log</h2>${m.simulated ? '<span class="badge sim">sim</span>' : ''}<span class="grow"></span><span class="faint">${this.questOpen ? '▾' : '▸'}</span></div>
      ${this.questOpen ? `<div class="quest-body">
        <div style="font-weight:600;line-height:1.35">${esc(m.goal)}</div>
        <div class="stepper">${order.map((_, i) => `<i class="${i < idx ? 'done' : i === idx ? 'on' : ''}"></i>`).join('')}</div>
        <div class="faint" style="display:flex;justify-content:space-between"><span>${esc(m.status)}</span><span>${tasks.length ? `${done}/${tasks.length} quests` : ''}</span></div>
        ${tasks.length ? `<div class="progress xp"><i style="width:${(done / tasks.length) * 100}%"></i></div>` : ''}
        ${active.map((t) => {
          const a = t.assigneeId ? store.agents.get(t.assigneeId) : undefined;
          return `<div style="display:grid;grid-template-columns:22px 1fr;gap:8px;align-items:center">${a ? headImg(a.skin, 'sm') : '<span></span>'}
            <div style="min-width:0"><div style="font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.title)}</div>
            <div class="progress" style="height:5px;margin-top:3px"><i style="width:${Math.round(t.progress * 100)}%"></i></div></div></div>`;
        }).join('')}
        <div style="display:flex;gap:6px"><button class="btn small gold" data-act="open">Open chamber</button><button class="btn small ghost" data-act="focus">Watch council</button></div>
      </div>` : ''}`;
  }

  // ---------------------------------------------------------------- toasts, help, welcome
  toast(text: string, level: 'info' | 'success' | 'warn' | 'error' = 'info'): void {
    const icon = { info: 'ℹ', success: '✔', warn: '⚠', error: '✖' }[level];
    const t = h('div', `toast panel ${level}`, `<span>${icon}</span><span>${esc(text)}</span>`);
    this.toasts.append(t);
    setTimeout(() => t.remove(), 4500);
  }

  showTip(text: string | null, x = 0, y = 0): void {
    if (!text) { this.tip.classList.add('hidden'); return; }
    this.tip.classList.remove('hidden');
    this.tip.innerHTML = text;
    this.tip.style.left = `${x}px`;
    this.tip.style.top = `${y - 14}px`;
  }

  get overlayOpen(): boolean { return !this.overlay.classList.contains('hidden'); }

  closeOverlay(): void { this.overlay.classList.add('hidden'); }

  showHelp(): void {
    const keys: [string, string][] = [
      ['T or /', 'Summon the council (command bar)'], ['1 – 9', 'Jump to hotbar villager'], ['Click', 'Select a villager in the world or list'],
      ['F', 'Follow / unfollow selected'], ['O · C · V', 'Overview · Council hall · Village'], ['M', 'Council chamber (missions, quests)'],
      ['N', 'Cycle day / night / auto'], ['Tab', 'Hide / show villager list'], ['Esc', 'Close panels, deselect'], ['Drag · Scroll', 'Orbit · zoom the camera (right-drag pans)'],
    ];
    this.overlay.innerHTML = `<div class="panel welcome">
      <h2>How the realm works</h2>
      <p class="lead">Every AI agent running on this computer lives here as a villager. Workers build at their plots; the council plans in the hall.</p>
      <div class="help-grid">${keys.map(([k, v]) => `<span class="kbd" style="justify-self:start">${k}</span><span>${v}</span>`).join('')}</div>
      <p class="muted" style="margin-top:16px">Blocks rising on a worker's plot are real edits. Scrolls flying from the hall are delegated quests. Detected agents are observed read-only; the realm only drives its own Claude API workers.</p>
      <div class="row-btns"><button class="btn primary" data-act="close">Got it</button></div></div>`;
    this.overlay.classList.remove('hidden');
  }

  showWelcome(): void {
    const info = this.ctx.store.info;
    this.overlay.innerHTML = `<div class="panel welcome">
      <h2>Welcome to your Agent Realm</h2>
      <p class="lead">A living world for every AI agent on this machine — and a council of frontier models to run them.</p>
      <ol>
        <li><b>Villagers are your agents.</b> Claude Code, Codex, Gemini CLI, Aider, Ollama and friends are discovered automatically. Click one to see exactly what it's doing.</li>
        <li><b>The council plans.</b> Type a goal (press <span class="kbd">T</span>). The council deliberates, writes a framework and task briefs, then delegates quests to workers.</li>
        <li><b>Workers build.</b> Watch scrolls fly, blocks rise and quests move across the board in the Council Chamber (<span class="kbd">M</span>).</li>
      </ol>
      ${info && !info.apiKeyPresent ? `<p class="muted">No <code>ANTHROPIC_API_KEY</code> found, so missions run as a <b>simulation</b>. Add a key and restart to let the real council deliberate.</p>` : ''}
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px">${EXAMPLES.map((x) => `<button class="chip" data-act="example" data-text="${esc(x)}">${esc(x)}</button>`).join('')}</div>
      <div class="row-btns"><button class="btn ghost" data-act="close">Explore first</button><button class="btn gold" data-act="example" data-text="">♛ Summon the council</button></div></div>`;
    this.overlay.classList.remove('hidden');
  }

  private showExamples(): void {
    this.toast('Describe a goal for the council, e.g. “' + EXAMPLES[0] + '”');
  }

  // ---------------------------------------------------------------- render
  render(): void {
    this.renderTop();
    this.renderRoster();
    this.renderHotbar();
    this.renderFeed();
    this.renderQuest();
    this.inspector.render();
    this.chamber.render();
  }
}

function platformName(p: string): string {
  return p === 'darwin' ? 'macOS' : p === 'win32' ? 'Windows' : p === 'linux' ? 'Linux' : p;
}
