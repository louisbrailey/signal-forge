import type { Agent, AgentRole, Mission, Task, TaskPriority } from '../shared/protocol.ts';
import { makeAgent } from './agents.ts';
import { ApiBrain, type Brain, type Plan, type RosterEntry } from './brain.ts';
import type { OverrideStore, RealmConfig } from './config.ts';
import { skinFor, titleFor } from './identity.ts';
import { SimBrain } from './simulation.ts';
import { Realm } from './state.ts';
import { now, truncate } from './util.ts';
import { appendContribution, isAbort, runTask, thinkingStream } from './workers.ts';

const PRIORITY_RANK: Record<TaskPriority, number> = { critical: 0, high: 1, normal: 2, low: 3 };
const CHAIR_ID = 'api:council-0';

export interface CouncilOptions {
  realm: Realm;
  config: RealmConfig;
  overrides?: OverrideStore;
  /** Override brains (tests). Defaults: ApiBrain when an API key is present, else SimBrain. */
  brain?: Brain;
  /** Simulation time compression (tests use a large value). */
  simSpeed?: number;
}

export class Council {
  private readonly realm: Realm;
  private readonly config: RealmConfig;
  private readonly overrides?: OverrideStore;
  private readonly brain: Brain;
  private readonly controllers = new Map<string, AbortController>();
  private readonly suggested = new Map<string, string>();
  private readonly manual = new Map<string, string>();
  private readonly busy = new Set<string>();
  private readonly running = new Map<string, string>(); // taskId → missionId
  private readonly finishing = new Set<string>();
  private readonly warnedNoWorkers = new Set<string>();
  private readonly timers = new Set<NodeJS.Timeout>();

  constructor(opts: CouncilOptions) {
    this.realm = opts.realm;
    this.config = opts.config;
    this.overrides = opts.overrides;
    this.brain = opts.brain ?? (opts.config.apiKeyPresent ? new ApiBrain() : new SimBrain({ speed: opts.simSpeed }));
  }

  get simulated(): boolean {
    return this.brain.simulated;
  }

  /** Council seats and the API work crew always exist as agents. */
  seedAgents(): void {
    const live = this.config.apiKeyPresent;
    this.config.council.forEach((seat, i) => {
      const id = `api:council-${i}`;
      const agent = makeAgent(
        { id, source: 'api', role: 'council', model: seat.model, live, controllable: true, title: seat.title, chair: i === 0, takenNames: this.realm.takenNames() },
        this.overrides,
      );
      if (agent.role !== 'council') agent.title = titleFor(agent);
      this.realm.upsertAgent(agent);
    });
    this.config.workers.forEach((model, i) => {
      this.realm.upsertAgent(makeAgent({ id: `api:worker-${i}`, source: 'api', role: 'worker', model, live, controllable: true, takenNames: this.realm.takenNames() }, this.overrides));
    });
  }

  // ── roster helpers ──────────────────────────────────────────────────────

  private councilMembers(): Agent[] {
    return [...this.realm.agents.values()].filter((a) => a.role === 'council' && a.controllable && a.status !== 'offline');
  }

  private chair(): Agent | undefined {
    const members = this.councilMembers();
    return members.find((a) => a.id === CHAIR_ID) ?? members[0];
  }

  private warden(): Agent | undefined {
    const members = this.councilMembers();
    return members.find((a) => a.title === 'Warden') ?? members[members.length - 1] ?? this.chair();
  }

  private seatTitle(agent: Agent): string {
    const m = /^api:council-(\d+)$/.exec(agent.id);
    const seat = m ? this.config.council[Number(m[1])] : undefined;
    return seat?.title ?? agent.title;
  }

  private roster(): RosterEntry[] {
    return [...this.realm.agents.values()]
      .filter((a) => a.role === 'worker' && (a.source === 'api' || a.live) && a.status !== 'offline')
      .map((a) => ({ id: a.id, name: a.name, model: a.model, source: a.source, controllable: a.controllable, status: a.status }));
  }

  // ── mission lifecycle ───────────────────────────────────────────────────

  summon(goal: string): Mission {
    const t = now();
    const mission = this.realm.upsertMission({
      id: Realm.newId(),
      goal: goal.trim(),
      status: 'convening',
      simulated: this.brain.simulated,
      createdAt: t,
      updatedAt: t,
      taskIds: [],
      transcript: [],
    });
    const controller = new AbortController();
    this.controllers.set(mission.id, controller);
    this.realm.toast('info', `The council convenes: ${truncate(mission.goal, 80)}${mission.simulated ? ' (simulated)' : ''}`);
    void this.deliberate(mission.id, controller.signal);
    return mission;
  }

  /** Resolves when the mission reaches a terminal state (used by tests). */
  waitFor(missionId: string, timeoutMs = 60_000): Promise<Mission> {
    return new Promise((resolve, reject) => {
      const terminal = (m?: Mission): boolean => !!m && ['complete', 'failed', 'cancelled'].includes(m.status);
      const current = this.realm.missions.get(missionId);
      if (terminal(current)) return resolve(current!);
      const timer = setTimeout(() => {
        this.realm.off('message', onMsg);
        reject(new Error(`Mission ${missionId} did not finish in ${timeoutMs}ms`));
      }, timeoutMs);
      const onMsg = (msg: { type: string; mission?: Mission }): void => {
        if (msg.type === 'mission' && msg.mission?.id === missionId && terminal(msg.mission)) {
          clearTimeout(timer);
          this.realm.off('message', onMsg);
          resolve(msg.mission);
        }
      };
      this.realm.on('message', onMsg);
    });
  }

  private failMission(missionId: string, error: string): void {
    const m = this.realm.patchMission(missionId, { status: 'failed', error });
    this.controllers.delete(missionId);
    for (const a of this.councilMembers()) if (a.status === 'thinking') this.realm.patchAgent(a.id, { status: 'idle' });
    if (m) this.realm.toast('error', `Mission failed: ${truncate(error, 120)}`);
  }

  private async deliberate(missionId: string, signal: AbortSignal): Promise<void> {
    const goal = this.realm.missions.get(missionId)?.goal ?? '';
    try {
      const members = this.councilMembers();
      const chair = this.chair();
      if (!members.length || !chair) throw new Error('The council is empty — promote an API agent to the council');

      this.realm.patchMission(missionId, { status: 'deliberating' });
      const results = await Promise.allSettled(
        members.map(async (m) => {
          this.realm.patchAgent(m.id, { status: 'thinking' });
          this.realm.pushActivity(m.id, { kind: 'plan', text: `Considering: ${truncate(goal, 80)}` });
          try {
            const gen = await this.brain.propose(
              { model: m.model ?? 'claude-opus-5', signal, onText: thinkingStream(this.realm, m.id) },
              { goal, seatTitle: this.seatTitle(m), memberName: m.name },
            );
            this.realm.addUsage(m.id, gen.tokensIn, gen.tokensOut);
            appendContribution(this.realm, missionId, { memberId: m.id, phase: 'proposal', text: gen.text });
            this.realm.pushActivity(m.id, { kind: 'message', text: 'Proposal ready', detail: gen.text });
            this.realm.patchAgent(m.id, { status: 'idle' });
            return { seatTitle: this.seatTitle(m), memberName: m.name, text: gen.text };
          } catch (err) {
            if (!isAbort(err, signal)) {
              this.realm.pushActivity(m.id, { kind: 'error', text: `Proposal failed: ${truncate(String((err as Error).message ?? err), 100)}` });
              this.realm.patchAgent(m.id, { status: 'error' });
              this.later(() => this.realm.getAgent(m.id)?.status === 'error' && this.realm.patchAgent(m.id, { status: 'idle' }), 5000);
            }
            throw err;
          }
        }),
      );
      if (signal.aborted) return;
      const proposals = results.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : []));
      if (!proposals.length) {
        const first = results.find((r): r is PromiseRejectedResult => r.status === 'rejected');
        throw first?.reason instanceof Error ? first.reason : new Error('No council member produced a proposal');
      }

      this.realm.patchMission(missionId, { status: 'planning' });
      const planner = this.chair() ?? chair;
      this.realm.patchAgent(planner.id, { status: 'thinking' });
      this.realm.pushActivity(planner.id, { kind: 'plan', text: `Synthesising ${proposals.length} proposals into a plan` });
      const synth = await this.brain.synthesize(
        { model: planner.model ?? 'claude-opus-5', signal, onText: thinkingStream(this.realm, planner.id) },
        { goal, proposals, roster: this.roster() },
      );
      if (signal.aborted) return;
      this.realm.addUsage(planner.id, synth.tokensIn, synth.tokensOut);
      const taskIds = this.createTasks(missionId, synth.plan);
      appendContribution(this.realm, missionId, { memberId: planner.id, phase: 'synthesis', text: renderPlan(synth.plan) });
      this.realm.patchMission(missionId, { status: 'executing', summary: synth.plan.summary, framework: synth.plan.framework, taskIds });
      this.realm.pushActivity(planner.id, { kind: 'plan', text: `Plan ready: ${taskIds.length} tasks` });
      this.realm.patchAgent(planner.id, { status: 'idle' });
      this.dispatch();
    } catch (err) {
      if (isAbort(err, signal)) return;
      this.failMission(missionId, err instanceof Error ? err.message : String(err));
    }
  }

  private createTasks(missionId: string, plan: Plan): string[] {
    const keyToId = new Map<string, string>();
    for (const t of plan.tasks) if (!keyToId.has(t.key)) keyToId.set(t.key, Realm.newId());
    const ids: string[] = [];
    const t0 = now();
    const seen = new Set<string>();
    for (const pt of plan.tasks) {
      const id = keyToId.get(pt.key)!;
      if (seen.has(id)) continue; // duplicate key: keep the first
      seen.add(id);
      const dependsOn = [...new Set(pt.dependsOn.map((k) => keyToId.get(k)).filter((d): d is string => !!d && d !== id))];
      const task: Task = {
        id,
        missionId,
        title: truncate(pt.title, 120),
        goal: pt.goal,
        instructions: pt.instructions,
        acceptance: pt.acceptance,
        dependsOn,
        status: 'backlog',
        priority: pt.priority,
        progress: 0,
        attempts: 0,
        createdAt: t0,
        updatedAt: t0,
      };
      const suggested = this.realm.getAgent(pt.suggestedAssignee);
      if (suggested?.controllable) this.suggested.set(id, suggested.id);
      this.realm.upsertTask(task);
      ids.push(id);
    }
    // Break dependency cycles defensively: a task may only depend on tasks listed before it.
    const order = new Map(ids.map((id, i) => [id, i]));
    for (const id of ids) {
      const task = this.realm.tasks.get(id)!;
      const deps = task.dependsOn.filter((d) => (order.get(d) ?? Infinity) < order.get(id)!);
      if (deps.length !== task.dependsOn.length) this.realm.patchTask(id, { dependsOn: deps });
    }
    return ids;
  }

  private isAvailable(agent: Agent | undefined, allowAnyRole = false): agent is Agent {
    return !!agent && agent.controllable && !this.busy.has(agent.id) && agent.status !== 'offline' && (allowAnyRole || agent.role === 'worker');
  }

  private pickWorker(task: Task): Agent | undefined {
    const manual = this.manual.get(task.id);
    if (manual) {
      const agent = this.realm.getAgent(manual);
      return this.isAvailable(agent, true) ? agent : undefined;
    }
    const suggested = this.realm.getAgent(this.suggested.get(task.id) ?? '');
    if (this.isAvailable(suggested)) return suggested;
    const free = [...this.realm.agents.values()].filter((a) => this.isAvailable(a));
    if (!free.length) return undefined;
    const big = PRIORITY_RANK[task.priority] <= 1 || task.instructions.length > 1200;
    const fit = free.find((a) => (big ? /sonnet|opus|fable/ : /haiku/).test(a.model ?? ''));
    return fit ?? free[0];
  }

  /** Assign every ready task to an idle controllable worker, across all executing missions. */
  dispatch(): void {
    for (const mission of this.realm.missions.values()) {
      if (mission.status !== 'executing' || !this.controllers.has(mission.id)) continue;
      const tasks = mission.taskIds.map((id) => this.realm.tasks.get(id)).filter((t): t is Task => !!t);
      const byId = new Map(tasks.map((t) => [t.id, t]));
      for (const t of tasks) {
        if (t.status !== 'backlog') continue;
        if (t.dependsOn.some((d) => ['failed', 'blocked'].includes(byId.get(d)?.status ?? ''))) this.realm.patchTask(t.id, { status: 'blocked' });
      }
      const ready = tasks
        .filter((t) => this.realm.tasks.get(t.id)?.status === 'backlog' && t.dependsOn.every((d) => byId.get(d)?.status === 'done'))
        .sort((a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]);
      for (const task of ready) {
        const worker = this.pickWorker(task);
        if (worker) this.start(mission, task, worker);
      }
      this.checkMission(mission.id);
    }
  }

  private start(mission: Mission, task: Task, worker: Agent): void {
    const controller = this.controllers.get(mission.id);
    const warden = this.warden();
    const chair = this.chair();
    if (!controller || !warden) return;
    this.busy.add(worker.id);
    this.running.set(task.id, mission.id);
    this.warnedNoWorkers.delete(mission.id);
    this.realm.patchTask(task.id, { status: 'assigned', assigneeId: worker.id });
    this.realm.patchAgent(worker.id, { status: 'waiting', currentTaskId: task.id });
    if (chair) {
      this.realm.broadcast({ type: 'delegate', fromId: chair.id, toId: worker.id, taskId: task.id });
      this.realm.pushActivity(chair.id, { kind: 'delegate', text: `Delegated "${truncate(task.title, 50)}" to ${worker.name}`, taskId: task.id });
    }
    void runTask({
      realm: this.realm,
      brain: this.brain,
      mission: this.realm.missions.get(mission.id) ?? mission,
      task: this.realm.tasks.get(task.id) ?? task,
      workerId: worker.id,
      wardenId: warden.id,
      signal: controller.signal,
    }).then((outcome) => {
      this.busy.delete(worker.id);
      this.running.delete(task.id);
      if (outcome === 'done') {
        this.later(() => this.realm.getAgent(worker.id)?.status === 'done' && this.realm.patchAgent(worker.id, { status: 'idle' }), 3000);
      } else if (outcome === 'failed') {
        this.realm.toast('warn', `Task failed: ${truncate(task.title, 80)}`);
        this.later(() => this.realm.getAgent(worker.id)?.status === 'error' && this.realm.patchAgent(worker.id, { status: 'idle' }), 5000);
      }
      this.dispatch();
    });
  }

  private checkMission(missionId: string): void {
    const mission = this.realm.missions.get(missionId);
    if (!mission || mission.status !== 'executing' || this.finishing.has(missionId)) return;
    const tasks = mission.taskIds.map((id) => this.realm.tasks.get(id)).filter((t): t is Task => !!t);
    if (tasks.length && tasks.every((t) => t.status === 'done')) {
      void this.finish(missionId);
      return;
    }
    const inFlight = [...this.running.values()].some((m) => m === missionId);
    if (inFlight) return;
    const waitingOnHandoff = tasks.some((t) => t.status === 'assigned');
    const runnable = tasks.some((t) => t.status === 'backlog' && t.dependsOn.every((d) => this.realm.tasks.get(d)?.status === 'done'));
    if (runnable) {
      const anyWorker = [...this.realm.agents.values()].some((a) => a.controllable && a.role === 'worker' && a.status !== 'offline');
      if (!anyWorker && !this.warnedNoWorkers.has(missionId)) {
        this.warnedNoWorkers.add(missionId);
        this.realm.toast('warn', 'No API workers available — assign tasks manually or demote a councillor to worker');
      }
      return;
    }
    const stuck = tasks.filter((t) => t.status === 'failed' || t.status === 'blocked');
    if (stuck.length && !waitingOnHandoff) {
      this.failMission(missionId, `${stuck.length} task(s) failed or blocked — retry them to continue`);
    }
  }

  private async finish(missionId: string): Promise<void> {
    this.finishing.add(missionId);
    const signal = this.controllers.get(missionId)?.signal ?? new AbortController().signal;
    try {
      const mission = this.realm.patchMission(missionId, { status: 'reviewing' });
      const chair = this.chair();
      if (!mission) return;
      if (chair) {
        this.realm.patchAgent(chair.id, { status: 'thinking' });
        this.realm.pushActivity(chair.id, { kind: 'review', text: 'Writing the final verdict' });
        const tasks = mission.taskIds.map((id) => this.realm.tasks.get(id)).filter((t): t is Task => !!t);
        const gen = await this.brain.verdict(
          { model: chair.model ?? 'claude-opus-5', signal, onText: thinkingStream(this.realm, chair.id) },
          { goal: mission.goal, summary: mission.summary ?? '', tasks: tasks.map((t) => ({ title: t.title, status: t.status, notes: t.review?.notes })) },
        );
        this.realm.addUsage(chair.id, gen.tokensIn, gen.tokensOut);
        appendContribution(this.realm, missionId, { memberId: chair.id, phase: 'verdict', text: gen.text });
        this.realm.pushActivity(chair.id, { kind: 'complete', text: `Mission complete: ${truncate(mission.goal, 70)}` });
        this.realm.patchAgent(chair.id, { status: 'idle' });
      }
      this.realm.patchMission(missionId, { status: 'complete' });
      this.controllers.delete(missionId);
      this.realm.toast('success', `Mission complete: ${truncate(mission.goal, 80)}`);
    } catch (err) {
      if (!isAbort(err, signal)) this.failMission(missionId, err instanceof Error ? err.message : String(err));
    } finally {
      this.finishing.delete(missionId);
    }
  }

  // ── client commands ─────────────────────────────────────────────────────

  cancel(missionId: string): void {
    const mission = this.realm.missions.get(missionId);
    if (!mission || ['complete', 'failed', 'cancelled'].includes(mission.status)) return;
    this.controllers.get(missionId)?.abort();
    this.controllers.delete(missionId);
    this.realm.patchMission(missionId, { status: 'cancelled' });
    for (const id of mission.taskIds) {
      const t = this.realm.tasks.get(id);
      if (t && t.status !== 'done') this.realm.patchTask(id, { status: 'failed' });
    }
    for (const a of this.councilMembers()) if (a.status === 'thinking') this.realm.patchAgent(a.id, { status: 'idle' });
    this.realm.toast('info', `Mission cancelled: ${truncate(mission.goal, 80)}`);
  }

  retryTask(taskId: string): void {
    const task = this.realm.tasks.get(taskId);
    if (!task) return;
    if (!['failed', 'blocked', 'assigned'].includes(task.status) || this.running.has(taskId)) {
      this.realm.toast('warn', 'Only failed, blocked or handed-off tasks can be retried');
      return;
    }
    this.reopen(task);
    this.dispatch();
  }

  private reopen(task: Task): void {
    const prevAssignee = task.assigneeId ? this.realm.getAgent(task.assigneeId) : undefined;
    if (prevAssignee && !prevAssignee.controllable && prevAssignee.currentTaskId === task.id) {
      this.realm.patchAgent(prevAssignee.id, { currentTaskId: undefined });
    }
    this.realm.patchTask(task.id, { status: 'backlog', progress: 0, attempts: 0, review: undefined, assigneeId: undefined });
    for (const t of this.realm.tasks.values()) {
      if (t.status === 'blocked' && t.missionId === task.missionId) this.realm.patchTask(t.id, { status: 'backlog' });
    }
    const mission = this.realm.missions.get(task.missionId);
    if (mission && (mission.status === 'failed' || mission.status === 'cancelled') && mission.taskIds.length) {
      this.controllers.set(mission.id, new AbortController());
      this.realm.patchMission(mission.id, { status: 'executing', error: undefined });
    }
  }

  assignTask(taskId: string, agentId: string): void {
    const task = this.realm.tasks.get(taskId);
    const agent = this.realm.getAgent(agentId);
    if (!task || !agent) return;
    if (this.running.has(taskId) || task.status === 'done') {
      this.realm.toast('warn', 'That task is already running or done');
      return;
    }
    if (agent.controllable) {
      this.manual.set(taskId, agentId);
      this.reopen(task);
      this.realm.toast('info', `${agent.name} will take "${truncate(task.title, 60)}" when free`);
      this.dispatch();
      return;
    }
    // Detected agents are observed, not driven: prepare a hand-off brief.
    this.manual.delete(taskId);
    if (['failed', 'blocked'].includes(task.status)) this.reopen(task);
    this.realm.patchTask(taskId, { status: 'assigned', assigneeId: agentId });
    this.realm.patchAgent(agentId, { currentTaskId: taskId });
    const chair = this.chair();
    if (chair) this.realm.broadcast({ type: 'delegate', fromId: chair.id, toId: agentId, taskId });
    const brief = `${task.title}\n\n${task.instructions}\n\nAcceptance:\n${task.acceptance.map((a) => `- ${a}`).join('\n')}`;
    this.realm.pushActivity(agentId, { kind: 'delegate', text: 'Instructions ready — hand off', detail: brief, taskId });
  }

  setRole(agentId: string, role: AgentRole): void {
    const agent = this.realm.getAgent(agentId);
    if (!agent || agent.role === role) return;
    const seat = /^api:council-(\d+)$/.exec(agentId);
    const next = { ...agent, role };
    const title = role === 'council' && seat ? this.config.council[Number(seat[1])]?.title ?? titleFor(next) : titleFor(next);
    this.realm.patchAgent(agentId, {
      role,
      title,
      skin: skinFor({ id: agentId, source: agent.source, role, model: agent.model, chair: agentId === CHAIR_ID }),
    });
    this.overrides?.set(agentId, { role });
    this.realm.toast('info', `${agent.name} is now ${role === 'council' ? 'on the council' : 'a worker'}`);
    this.dispatch();
  }

  rename(agentId: string, name: string): void {
    const clean = name.replace(/\s+/g, ' ').trim().slice(0, 32);
    if (!clean || !this.realm.getAgent(agentId)) return;
    this.realm.patchAgent(agentId, { name: clean });
    this.overrides?.set(agentId, { name: clean });
  }

  private later(fn: () => unknown, ms: number): void {
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      fn();
    }, ms);
    timer.unref?.();
    this.timers.add(timer);
  }

  dispose(): void {
    for (const c of this.controllers.values()) c.abort();
    for (const t of this.timers) clearTimeout(t);
    this.timers.clear();
  }
}

function renderPlan(plan: Plan): string {
  const lines = [
    plan.summary,
    '',
    '### Framework',
    plan.framework.architecture,
    '',
    ...(plan.framework.principles.length ? ['**Principles**', ...plan.framework.principles.map((p) => `- ${p}`), ''] : []),
    ...(plan.framework.milestones.length ? ['**Milestones**', ...plan.framework.milestones.map((m, i) => `${i + 1}. ${m}`), ''] : []),
    '### Tasks',
    ...plan.tasks.map((t) => `- **${t.title}** (${t.priority})${t.dependsOn.length ? ` — after ${t.dependsOn.join(', ')}` : ''}`),
  ];
  return lines.join('\n');
}
