import type { Agent } from '../../shared/protocol';
import type { Ctx } from './context';
import { KIND_ICON, SOURCE_LABEL, STATUS_LABEL, ago, clock, compact, esc, h, headImg, modelLabel, statusDot } from './util';

/** Right-hand drawer: everything about the selected villager. */
export class Inspector {
  readonly el = h('aside', 'inspector panel closed');
  private heroFor = '';
  private hero = h('div', 'ins-hero');
  private actions = h('div', 'ins-actions');
  private body = h('div', 'ins-body scroll');

  constructor(private ctx: Ctx) {
    const head = h('div', 'panel-head', `<h2>Villager</h2><span class="grow"></span><button class="btn ghost small" data-act="close" title="Close (Esc)">✕</button>`);
    this.el.append(head, this.hero, this.actions, this.body);
    this.el.setAttribute('aria-label', 'Agent inspector');

    this.el.addEventListener('click', (e) => {
      const btn = (e.target as HTMLElement).closest<HTMLElement>('[data-act]');
      if (!btn) return;
      const a = this.agent();
      const act = btn.dataset.act;
      if (act === 'close') return ctx.select(null);
      if (!a) return;
      if (act === 'follow') ctx.follow(ctx.store.followId === a.id ? null : a.id);
      if (act === 'role') ctx.store.send({ type: 'set_role', agentId: a.id, role: a.role === 'council' ? 'worker' : 'council' });
      if (act === 'task' && a.currentTaskId) {
        const t = ctx.store.tasks.get(a.currentTaskId);
        ctx.openChamber(t?.missionId, a.currentTaskId);
      }
      if (act === 'complete' && a.currentTaskId) ctx.store.send({ type: 'complete_task', taskId: a.currentTaskId });
      if (act === 'copy' && a.currentTaskId) {
        const t = ctx.store.tasks.get(a.currentTaskId);
        if (t) {
          const brief = `# ${t.title}\n\n${t.goal}\n\n${t.instructions}\n\n## Acceptance\n${t.acceptance.map((x) => `- ${x}`).join('\n')}`;
          void navigator.clipboard?.writeText(brief).then(() => ctx.store.log({ text: `Copied brief for “${t.title}” — paste it into ${a.name}'s session`, tone: 'success' }));
          ctx.store.changed();
        }
      }
    });

    this.hero.addEventListener('change', (e) => {
      const input = e.target as HTMLInputElement;
      const a = this.agent();
      if (a && input.name === 'name' && input.value.trim()) ctx.store.send({ type: 'rename_agent', agentId: a.id, name: input.value.trim().slice(0, 24) });
    });
    this.hero.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
      e.stopPropagation();
    });
  }

  private agent(): Agent | undefined {
    const id = this.ctx.store.selectedId;
    return id ? this.ctx.store.agents.get(id) : undefined;
  }

  render(): void {
    const a = this.agent();
    this.el.classList.toggle('closed', !a);
    if (!a) { this.heroFor = ''; return; }
    const { store } = this.ctx;

    // Hero is re-rendered only when it would visibly change, so the rename field keeps focus.
    const heroKey = `${a.id}|${a.name}|${a.title}|${a.role}|${a.status}|${a.live}|${a.model}|${JSON.stringify(a.skin)}`;
    if (heroKey !== this.heroFor && !this.hero.contains(document.activeElement)) {
      this.heroFor = heroKey;
      const badges = [
        a.role === 'council' ? '<span class="badge gold">♛ Council</span>' : '<span class="badge api">Worker</span>',
        a.live ? '<span class="badge live">Live</span>' : '<span class="badge demo">Simulated</span>',
        a.model ? `<span class="badge sim" title="${esc(a.model)}">${esc(modelLabel(a.model))}</span>` : '',
      ].join('');
      this.hero.innerHTML = `
        ${headImg(a.skin, 'lg')}
        <div style="min-width:0">
          <h3>${statusDot(a.status)}<input name="name" value="${esc(a.name)}" aria-label="Rename villager" maxlength="24" spellcheck="false"/></h3>
          <div class="title">${esc(a.title)} · ${esc(STATUS_LABEL[a.status])}</div>
          <div class="badges">${badges}</div>
        </div>`;
    }

    const following = store.followId === a.id;
    this.actions.innerHTML = `
      <button class="btn small ${following ? 'gold' : ''}" data-act="follow" title="Camera follows this villager (F)">${following ? '◉ Following' : '◎ Follow'}</button>
      <button class="btn small" data-act="role" title="Council members plan & delegate; workers execute">${a.role === 'council' ? '↓ Move to workforce' : '♛ Promote to council'}</button>
      ${a.currentTaskId ? `<button class="btn small" data-act="task">📜 Open task</button>` : ''}
      ${a.currentTaskId && !a.controllable ? `<button class="btn small primary" data-act="copy" title="This agent is observed, not driven — hand it the brief">⧉ Copy brief</button>
        <button class="btn small" data-act="complete" title="Confirm the hand-off quest is finished">✔ Mark done</button>` : ''}`;

    const task = a.currentTaskId ? store.tasks.get(a.currentTaskId) : undefined;
    const p = a.process;
    const facts: [string, string | undefined][] = [
      ['Source', SOURCE_LABEL[a.source]],
      ['Model', a.model],
      ['Project', a.project],
      ['Directory', a.cwd],
      ['PID', p ? String(p.pid) : undefined],
      ['CPU / Mem', p ? `${p.cpu.toFixed(1)}% · ${Math.round(p.memMb)} MB` : undefined],
      ['Up', p?.startedAt ? ago(p.startedAt, store.now) : ago(a.createdAt, store.now)],
      ['Last seen', ago(a.lastActivityAt, store.now) + ' ago'],
    ];
    const recent = [...a.recent].reverse();
    this.body.innerHTML = `
      <div class="section">
        <h4>Right now</h4>
        <div class="now">${statusDot(a.status)}<div class="txt">${esc(a.currentAction || (a.status === 'idle' ? 'Taking a breather.' : STATUS_LABEL[a.status]))}</div></div>
        ${task ? `
          <div class="card" style="margin-top:8px;padding:9px 10px">
            <div style="display:flex;justify-content:space-between;gap:8px;margin-bottom:6px"><b style="font-size:12.5px">${esc(task.title)}</b><span class="faint" style="font-size:11px">${esc(task.status.replace('_', ' '))}</span></div>
            <div class="progress xp"><i style="width:${Math.round(task.progress * 100)}%"></i></div>
          </div>` : ''}
      </div>
      <div class="section">
        <h4>Stats</h4>
        <div class="statgrid">
          <div><b>${compact(a.stats.toolCalls)}</b><span>Actions</span></div>
          <div><b>${compact(a.stats.tasksDone)}</b><span>Quests</span></div>
          <div><b>${compact(a.stats.tokensIn)}</b><span>Tok in</span></div>
          <div><b>${compact(a.stats.tokensOut)}</b><span>Tok out</span></div>
        </div>
      </div>
      <div class="section">
        <h4>Details</h4>
        <dl class="kv">${facts.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd title="${esc(v)}">${esc(v)}</dd>`).join('')}</dl>
      </div>
      <div class="section">
        <h4>Activity</h4>
        ${recent.length ? `<ul class="timeline">${recent.map((r) => `
          <li><span class="ico k-${r.kind}">${KIND_ICON[r.kind]}</span>
            <div><div class="t">${esc(r.text)}</div>${r.detail ? `<div class="d">${esc(r.detail.slice(0, 300))}</div>` : ''}</div>
            <time title="${clock(r.ts)}">${ago(r.ts, store.now)}</time></li>`).join('')}</ul>`
          : `<div class="empty">No activity yet. When ${esc(a.name)} starts working, every read, edit and command shows up here.</div>`}
      </div>`;
  }
}
