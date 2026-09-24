import type { Mission, MissionStatus, Task, TaskStatus } from '../../shared/protocol';
import type { Ctx } from './context';
import { ago, esc, h, headImg, md, modelLabel } from './util';

const PHASES: { key: MissionStatus; label: string }[] = [
  { key: 'convening', label: 'Convene' },
  { key: 'deliberating', label: 'Deliberate' },
  { key: 'planning', label: 'Plan' },
  { key: 'executing', label: 'Execute' },
  { key: 'reviewing', label: 'Review' },
  { key: 'complete', label: 'Complete' },
];

const COLUMNS: { label: string; match: TaskStatus[] }[] = [
  { label: 'Backlog', match: ['backlog', 'blocked'] },
  { label: 'Assigned', match: ['assigned'] },
  { label: 'In progress', match: ['in_progress'] },
  { label: 'Review', match: ['review'] },
  { label: 'Done', match: ['done', 'failed'] },
];

type Tab = 'council' | 'framework' | 'board';

/** Full-screen "Council Chamber": missions, deliberation transcript, framework and the quest board. */
export class Chamber {
  readonly el = h('div', 'sheet-wrap hidden');
  private sheet = h('div', 'sheet panel');
  private list = h('div', 'missions scroll');
  private main = h('div', 'mission');
  private tab: Tab = 'council';
  private taskId: string | null = null;
  private lastKey = '';

  constructor(private ctx: Ctx) {
    const head = h('div', 'sheet-head', `
      <span style="font-size:22px">♛</span><h2>Council Chamber</h2>
      <span class="faint" id="ch-sub"></span><span style="flex:1"></span>
      <button class="btn gold small" data-act="new">✦ New mission</button>
      <button class="btn ghost small" data-act="close" title="Close (Esc)">✕</button>`);
    const body = h('div', 'sheet-main');
    body.append(this.list, this.main);
    this.sheet.append(head, body);
    this.el.append(this.sheet);
    this.el.setAttribute('role', 'dialog');
    this.el.setAttribute('aria-label', 'Council chamber');

    this.el.addEventListener('mousedown', (e) => { if (e.target === this.el) ctx.closeChamber(); });
    this.el.addEventListener('click', (e) => this.onClick(e));
    this.el.addEventListener('change', (e) => {
      const sel = e.target as HTMLSelectElement;
      if (sel.name === 'assignee' && sel.value && this.taskId) ctx.store.send({ type: 'assign_task', taskId: this.taskId, agentId: sel.value });
    });
  }

  get open(): boolean { return !this.el.classList.contains('hidden'); }

  show(missionId?: string, taskId?: string): void {
    if (missionId) this.ctx.store.missionId = missionId;
    if (taskId) { this.taskId = taskId; this.tab = 'board'; }
    this.el.classList.remove('hidden');
    this.lastKey = '';
    this.render();
  }

  hide(): void { this.el.classList.add('hidden'); }

  private onClick(e: MouseEvent): void {
    const t = (e.target as HTMLElement).closest<HTMLElement>('[data-act],[data-mission],[data-task],[data-tab],[data-agent]');
    if (!t) return;
    const { store } = this.ctx;
    if (t.dataset.act === 'close') return this.ctx.closeChamber();
    if (t.dataset.act === 'new') { this.ctx.closeChamber(); document.querySelector<HTMLInputElement>('.command input')?.focus(); return; }
    if (t.dataset.act === 'cancel' && store.missionId) store.send({ type: 'cancel_mission', missionId: store.missionId });
    if (t.dataset.act === 'retry' && this.taskId) store.send({ type: 'retry_task', taskId: this.taskId });
    if (t.dataset.act === 'untask') this.taskId = null;
    if (t.dataset.mission) { store.missionId = t.dataset.mission; this.taskId = null; }
    if (t.dataset.task) { this.taskId = t.dataset.task; this.tab = 'board'; }
    if (t.dataset.tab) this.tab = t.dataset.tab as Tab;
    if (t.dataset.agent) { this.ctx.closeChamber(); this.ctx.select(t.dataset.agent, { follow: true }); return; }
    this.lastKey = '';
    this.render();
  }

  render(): void {
    if (!this.open) return;
    const { store } = this.ctx;
    const missions = [...store.missions.values()].sort((a, b) => b.createdAt - a.createdAt);
    const m = store.missionId ? store.missions.get(store.missionId) : undefined;
    const tasks = m ? store.missionTasks(m) : [];
    // Skip DOM work when nothing visible changed (the store ticks often during execution).
    const key = JSON.stringify([missions.map((x) => [x.id, x.status, x.updatedAt]), this.tab, this.taskId, tasks.map((t) => [t.status, Math.round(t.progress * 50), t.updatedAt, t.assigneeId]), store.info?.apiKeyPresent]);
    if (key === this.lastKey) return;
    // Preserve scroll of the tab body across re-renders.
    const scroller = this.main.querySelector('.tab-body');
    const scrollTop = scroller?.scrollTop ?? 0;
    this.lastKey = key;

    const sub = this.sheet.querySelector('#ch-sub')!;
    sub.textContent = store.info?.apiKeyPresent ? `Council: ${store.info.councilModels.map(modelLabel).join(' · ')}` : 'Simulated council — add ANTHROPIC_API_KEY for real deliberation';

    this.list.innerHTML = missions.length
      ? missions.map((x) => `
        <div class="mission-item ${x.id === m?.id ? 'sel' : ''}" data-mission="${x.id}">
          <div class="g">${esc(x.goal)}</div>
          <div class="m">${statusBadge(x.status)}${x.simulated ? '<span class="badge sim">sim</span>' : ''}<span>${ago(x.createdAt, store.now)} ago</span></div>
        </div>`).join('')
      : `<div class="empty">No missions yet.<br/><br/>Type a goal in the command bar (press <span class="kbd">T</span>) and the council will convene, design a framework, write task briefs and delegate them to workers.</div>`;

    if (!m) {
      this.main.innerHTML = `<div class="empty" style="padding:40px"><h3 class="pixel" style="font-size:20px;margin:0 0 8px;color:var(--text)">The council awaits a goal.</h3>
        Describe what you want built — “Design a REST API for my garden sensors”, “Plan a launch checklist for my app” — and the most powerful models deliberate, agree on a framework, and hand out quests.</div>`;
      return;
    }

    const idx = PHASES.findIndex((p) => p.key === m.status);
    const done = tasks.filter((t) => t.status === 'done').length;
    const live = !['complete', 'failed', 'cancelled'].includes(m.status);
    this.main.innerHTML = `
      <div class="mission-top">
        <p class="goal">${esc(m.goal)}</p>
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
          <div class="phases">${PHASES.map((p, i) => `<span class="phase ${i < idx || m.status === 'complete' ? 'done' : ''} ${i === idx ? 'on' : ''}">${p.label}</span>`).join('')}</div>
          ${m.status === 'failed' || m.status === 'cancelled' ? statusBadge(m.status) : ''}
          <span style="flex:1"></span>
          ${tasks.length ? `<span class="faint">${done}/${tasks.length} quests</span><div class="progress xp" style="width:140px"><i style="width:${(done / tasks.length) * 100}%"></i></div>` : ''}
          ${live ? `<button class="btn danger small" data-act="cancel">Disband</button>` : ''}
        </div>
        ${m.error ? `<div style="color:var(--redstone);margin-top:8px">${esc(m.error)}</div>` : ''}
      </div>
      <div class="tabs">
        ${tabBtn('council', `Deliberation (${m.transcript.length})`, this.tab)}
        ${tabBtn('framework', 'Framework', this.tab)}
        ${tabBtn('board', `Quest board (${tasks.length})`, this.tab)}
      </div>
      <div class="tab-body scroll">${this.tab === 'council' ? this.transcript(m) : this.tab === 'framework' ? framework(m) : this.board(tasks)}</div>`;
    const nb = this.main.querySelector('.tab-body');
    if (nb) nb.scrollTop = scrollTop;
  }

  private transcript(m: Mission): string {
    const { store } = this.ctx;
    if (!m.transcript.length) return `<div class="empty">The council is taking their seats…</div>`;
    return `<div class="transcript">${m.transcript.map((c) => {
      const a = store.agents.get(c.memberId);
      return `<div class="speech ${c.phase}">
        <div>${a ? `<span data-agent="${a.id}" style="cursor:pointer">${headImg(a.skin)}</span>` : ''}</div>
        <div class="bubble">
          <div class="who">${esc(a?.name ?? 'Council')}<span class="faint" style="font-weight:400">${esc(a?.title ?? '')}${a?.model ? ` · ${esc(modelLabel(a.model))}` : ''}</span><span class="phase-tag">· ${c.phase}</span><span style="flex:1"></span><span class="faint" style="font-weight:400;font-size:11px">${ago(c.ts, store.now)} ago</span></div>
          <div class="md">${md(c.text)}</div>
        </div></div>`;
    }).join('')}</div>`;
  }

  private board(tasks: Task[]): string {
    const { store } = this.ctx;
    const detail = this.taskId ? store.tasks.get(this.taskId) : undefined;
    if (detail) return this.taskDetail(detail);
    if (!tasks.length) return `<div class="empty">No quests yet — the council is still planning.</div>`;
    return `<div class="board">${COLUMNS.map((col) => {
      const items = tasks.filter((t) => col.match.includes(t.status));
      return `<div class="col"><div class="col-head"><span>${col.label}</span><span>${items.length}</span></div>
        <div class="col-body scroll">${items.map((t) => {
          const a = t.assigneeId ? store.agents.get(t.assigneeId) : undefined;
          return `<div class="task" data-task="${t.id}">
            <div class="tt">${t.status === 'failed' ? '✖ ' : t.status === 'done' ? '✔ ' : ''}${esc(t.title)}</div>
            ${t.status === 'in_progress' ? `<div class="progress xp"><i style="width:${Math.round(t.progress * 100)}%"></i></div>` : ''}
            <div class="tm"><span class="prio ${t.priority}">${t.priority}</span>${t.dependsOn.length ? `<span title="Depends on ${t.dependsOn.length} quest(s)">⛓ ${t.dependsOn.length}</span>` : ''}<span style="flex:1"></span>${a ? `${headImg(a.skin, 'sm')}<span>${esc(a.name)}</span>` : '<span>unassigned</span>'}</div>
          </div>`;
        }).join('')}</div></div>`;
    }).join('')}</div>`;
  }

  private taskDetail(t: Task): string {
    const { store } = this.ctx;
    const a = t.assigneeId ? store.agents.get(t.assigneeId) : undefined;
    const reviewer = t.review ? store.agents.get(t.review.reviewerId) : undefined;
    const workers = store.sortedAgents().filter((x) => x.role === 'worker' && x.status !== 'offline');
    const deps = t.dependsOn.map((id) => store.tasks.get(id)).filter((x): x is Task => !!x);
    return `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <button class="btn ghost small" data-act="untask">← Board</button>
        <h3 class="pixel" style="margin:0;font-size:18px;flex:1">${esc(t.title)}</h3>
        <span class="prio ${t.priority}">${t.priority}</span>${statusBadge(t.status)}
      </div>
      <div class="task-detail">
        <div class="card"><h5>Goal</h5><div class="md">${md(t.goal)}</div></div>
        <div class="card"><h5>Assignment</h5>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">${a ? `<span data-agent="${a.id}" style="cursor:pointer;display:flex;gap:8px;align-items:center">${headImg(a.skin)}<b>${esc(a.name)}</b></span><span class="faint">${esc(modelLabel(a.model) || a.title)}</span>` : '<span class="faint">Unassigned</span>'}</div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <select class="pick" name="assignee" aria-label="Reassign"><option value="">Reassign to…</option>${workers.map((w) => `<option value="${w.id}">${esc(w.name)} — ${esc(modelLabel(w.model) || w.title)}${w.controllable ? '' : ' (hand-off)'}</option>`).join('')}</select>
            ${t.status === 'failed' || t.status === 'done' ? `<button class="btn small" data-act="retry">↻ Run again</button>` : ''}
          </div>
          ${t.status === 'in_progress' ? `<div class="progress xp" style="margin-top:10px"><i style="width:${Math.round(t.progress * 100)}%"></i></div>` : ''}
          ${deps.length ? `<div style="margin-top:10px" class="faint">Depends on: ${deps.map((d) => `<a data-task="${d.id}" style="cursor:pointer;color:var(--text-2);text-decoration:underline">${esc(d.title)}</a>`).join(', ')}</div>` : ''}
        </div>
        <div class="card full"><h5>Instructions</h5><div class="md">${md(t.instructions)}</div></div>
        <div class="card"><h5>Acceptance criteria</h5><ul class="accept ${t.status === 'done' ? 'ok' : ''}">${t.acceptance.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>
        <div class="card"><h5>Review</h5>${t.review ? `<div style="margin-bottom:6px">${t.review.verdict === 'approved' ? '<span class="badge live">Approved</span>' : '<span class="badge demo">Revise</span>'} <span class="faint">by ${esc(reviewer?.name ?? 'the Warden')}</span></div><div class="md">${md(t.review.notes)}</div>` : '<span class="faint">Not reviewed yet.</span>'}</div>
        <div class="card full"><h5>Deliverable</h5>${t.output ? `<div class="md">${md(t.output)}</div>` : `<span class="faint">${t.status === 'in_progress' ? 'Being written…' : 'Nothing delivered yet.'}</span>`}</div>
      </div>`;
  }
}

function tabBtn(key: Tab, label: string, cur: Tab): string {
  return `<button class="tab ${key === cur ? 'on' : ''}" data-tab="${key}">${esc(label)}</button>`;
}

function framework(m: Mission): string {
  if (!m.framework && !m.summary) return `<div class="empty">The chair publishes the framework once the council has deliberated.</div>`;
  const f = m.framework;
  return `
    ${m.summary ? `<div class="card" style="margin-bottom:14px"><h5>Summary</h5><div class="md">${md(m.summary)}</div></div>` : ''}
    ${f ? `<div class="framework">
      <div class="card"><h5>Architecture</h5><div class="md">${md(f.architecture)}</div></div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="card"><h5>Principles</h5><ul class="md" style="margin:0;padding-left:18px">${f.principles.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>
        <div class="card"><h5>Milestones</h5><ol class="milestones">${f.milestones.map((p) => `<li><span>${esc(p)}</span></li>`).join('')}</ol></div>
      </div></div>` : ''}`;
}

function statusBadge(s: string): string {
  const cls = s === 'complete' || s === 'done' ? 'live' : s === 'failed' || s === 'cancelled' ? 'demo' : s === 'executing' || s === 'in_progress' ? 'api' : 'gold';
  return `<span class="badge ${cls}">${esc(s.replace('_', ' '))}</span>`;
}
