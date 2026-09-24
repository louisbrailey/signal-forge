import type { Mission, Task } from '../shared/protocol.ts';
import type { Brain, BrainCall, Review } from './brain.ts';
import type { Realm } from './state.ts';
import { AbortedError, firstLine, now, truncate } from './util.ts';

const PROGRESS_MS = 500;
const SNIPPET_MS = 1500;
export const MAX_ATTEMPTS = 2;

/** Concurrent reviews per reviewer, so the Warden only goes idle after the last one. */
const reviewing = new Map<string, number>();

/** Stream callback for council members: a short "…snippet" think activity at most every ~1.5s. */
export function thinkingStream(realm: Realm, agentId: string, taskId?: string): (delta: string) => void {
  let buffer = '';
  let last = 0;
  return (delta) => {
    buffer = (buffer + delta).slice(-400);
    if (buffer.length < 40 || now() - last < SNIPPET_MS) return;
    last = now();
    const tail = buffer.slice(-160).replace(/\s+/g, ' ').trim();
    const snippet = tail.split(' ').slice(1).join(' ') || tail;
    if (snippet) realm.pushActivity(agentId, { kind: 'think', text: `…${truncate(snippet, 90)}`, ...(taskId ? { taskId } : {}) });
  };
}

export function isAbort(err: unknown, signal: AbortSignal): boolean {
  return signal.aborted || err instanceof AbortedError || (err instanceof Error && err.message === 'Request cancelled');
}

export interface WorkerContext {
  realm: Realm;
  brain: Brain;
  mission: Mission;
  task: Task;
  workerId: string;
  wardenId: string;
  signal: AbortSignal;
}

export type TaskOutcome = 'done' | 'failed' | 'aborted';

async function produce(ctx: WorkerContext, attempt: number, reviseNotes?: string): Promise<string> {
  const { realm, brain, mission, workerId, signal } = ctx;
  const task = realm.tasks.get(ctx.task.id) ?? ctx.task;
  const worker = realm.getAgent(workerId);
  if (!worker) throw new Error('Worker left the realm');
  const dependencies = task.dependsOn
    .map((id) => realm.tasks.get(id))
    .filter((t): t is Task => Boolean(t?.output))
    .map((t) => ({ title: t.title, output: t.output ?? '' }));
  const input = {
    goal: mission.goal,
    summary: mission.summary ?? '',
    framework: mission.framework,
    task: { title: task.title, goal: task.goal, instructions: task.instructions, acceptance: task.acceptance },
    dependencies,
    reviseNotes,
    workerName: worker.name,
  };

  realm.patchTask(task.id, { status: 'in_progress', assigneeId: workerId, attempts: attempt, progress: 0.02 });
  realm.patchAgent(workerId, { status: 'working', currentTaskId: task.id });
  realm.pushActivity(workerId, {
    kind: 'plan',
    text: attempt > 1 ? `Revising: ${truncate(task.title, 70)}` : `Starting: ${truncate(task.title, 70)}`,
    taskId: task.id,
  });

  const expected = Math.max(500, brain.expectedChars(input));
  let text = '';
  let scanFrom = 0;
  let lastProgress = 0;
  let lastSnippet = now();
  const call: BrainCall = {
    model: worker.model ?? 'claude-sonnet-5',
    signal,
    onText: (delta) => {
      text += delta;
      const t = now();
      // Scan complete lines only; a new markdown heading is the most legible progress signal.
      let heading: string | undefined;
      let code = false;
      const lastNl = text.lastIndexOf('\n');
      if (lastNl >= scanFrom) {
        const chunk = text.slice(scanFrom, lastNl + 1);
        scanFrom = lastNl + 1;
        for (const m of chunk.matchAll(/^#{1,3} +(.+)$/gm)) heading = m[1];
        code = chunk.includes('```');
      }
      if (heading && t - lastSnippet > 400) {
        lastSnippet = t;
        const kind = code || /code|impl|build|test/i.test(heading) ? 'edit' : 'message';
        realm.pushActivity(workerId, { kind, text: `Drafting: ${truncate(heading.trim(), 70)}`, taskId: task.id });
      } else if (t - lastSnippet > SNIPPET_MS * 2) {
        lastSnippet = t;
        const line = firstLine(text.slice(-200).split('\n').slice(-2).join(' '), 80);
        if (line) realm.pushActivity(workerId, { kind: 'message', text: `Writing: ${line}`, taskId: task.id });
      }
      if (t - lastProgress >= PROGRESS_MS) {
        lastProgress = t;
        realm.patchTask(task.id, { progress: Math.min(0.95, Math.max(0.02, text.length / expected)) });
      }
    },
  };
  const gen = await brain.execute(call, input);
  realm.addUsage(workerId, gen.tokensIn, gen.tokensOut);
  if (!gen.text.trim()) throw new Error('Worker produced an empty deliverable');
  return gen.text;
}

async function review(ctx: WorkerContext, output: string, attempt: number): Promise<Review> {
  const { realm, brain, mission, wardenId, signal } = ctx;
  const task = realm.tasks.get(ctx.task.id) ?? ctx.task;
  const warden = realm.getAgent(wardenId);
  reviewing.set(wardenId, (reviewing.get(wardenId) ?? 0) + 1);
  realm.patchAgent(wardenId, { status: 'thinking' });
  realm.pushActivity(wardenId, { kind: 'review', text: `Reviewing: ${truncate(task.title, 70)}`, taskId: task.id });
  try {
    const res = await brain.review(
      { model: warden?.model ?? 'claude-opus-5', signal, onText: thinkingStream(realm, wardenId, task.id) },
      { goal: mission.goal, task: { title: task.title, goal: task.goal, acceptance: task.acceptance }, output, attempt },
    );
    realm.addUsage(wardenId, res.tokensIn, res.tokensOut);
    return { verdict: res.verdict, notes: res.notes };
  } finally {
    const left = (reviewing.get(wardenId) ?? 1) - 1;
    reviewing.set(wardenId, left);
    if (left <= 0) realm.patchAgent(wardenId, { status: 'idle' });
  }
}

/**
 * Run one task on an API worker: produce → deliver → Warden review → (optional single revision) → done.
 * Never throws; failures are recorded on the task and reported as the outcome.
 */
export async function runTask(ctx: WorkerContext): Promise<TaskOutcome> {
  const { realm, workerId, wardenId, signal } = ctx;
  const taskId = ctx.task.id;
  let notes: string | undefined;
  try {
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      const output = await produce(ctx, attempt, notes);
      realm.patchTask(taskId, { status: 'review', progress: 1, output });
      realm.patchAgent(workerId, { status: 'waiting' });
      realm.pushActivity(workerId, { kind: 'complete', text: `Delivered: ${truncate(ctx.task.title, 70)}`, taskId });
      realm.broadcast({ type: 'deliver', fromId: workerId, toId: wardenId, taskId });

      const verdict = await review(ctx, output, attempt);
      const final = verdict.verdict === 'approved' || attempt === MAX_ATTEMPTS;
      realm.patchTask(taskId, { review: { reviewerId: wardenId, verdict: verdict.verdict, notes: verdict.notes } });
      appendContribution(realm, ctx.mission.id, {
        memberId: wardenId,
        phase: 'review',
        text: `**${ctx.task.title}** — ${verdict.verdict === 'approved' ? 'approved' : final ? 'accepted with notes' : 'revision requested'}: ${verdict.notes}`,
      });
      realm.pushActivity(wardenId, {
        kind: 'review',
        text: `${verdict.verdict === 'approved' ? 'Approved' : final ? 'Accepted with notes' : 'Revise'}: ${truncate(ctx.task.title, 60)}`,
        detail: verdict.notes,
        taskId,
      });
      if (final) break;
      notes = verdict.notes;
    }
    realm.patchTask(taskId, { status: 'done', progress: 1 });
    const worker = realm.getAgent(workerId);
    if (worker) {
      realm.patchAgent(workerId, {
        status: 'done',
        currentTaskId: undefined,
        stats: { ...worker.stats, tasksDone: worker.stats.tasksDone + 1 },
      });
    }
    return 'done';
  } catch (err) {
    const aborted = isAbort(err, signal);
    const message = err instanceof Error ? err.message : String(err);
    realm.patchTask(taskId, { status: 'failed' });
    realm.patchAgent(workerId, { status: aborted ? 'idle' : 'error', currentTaskId: undefined });
    realm.pushActivity(workerId, {
      kind: aborted ? 'system' : 'error',
      text: aborted ? `Stopped: ${truncate(ctx.task.title, 70)}` : `Failed: ${truncate(message, 100)}`,
      taskId,
    });
    return aborted ? 'aborted' : 'failed';
  }
}

export function appendContribution(
  realm: Realm,
  missionId: string,
  c: { memberId: string; phase: 'proposal' | 'synthesis' | 'review' | 'verdict'; text: string },
): void {
  const mission = realm.missions.get(missionId);
  if (!mission) return;
  realm.upsertMission({
    ...mission,
    transcript: [...mission.transcript, { id: crypto.randomUUID(), ts: now(), ...c }],
  });
}
