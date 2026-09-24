import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { ServerMessage } from '../shared/protocol.ts';
import { Council } from '../server/council.ts';
import { loadConfig } from '../server/config.ts';
import { SimBrain, SIM_BANNER } from '../server/simulation.ts';
import { Realm } from '../server/state.ts';
import { seededRandom } from '../server/util.ts';

function setup(seed: string) {
  const config = loadConfig('/nonexistent', {});
  assert.equal(config.apiKeyPresent, false);
  const realm = new Realm({
    version: 'test',
    platform: process.platform,
    hostname: 'test',
    apiKeyPresent: false,
    demoPopulation: false,
    councilModels: config.council.map((s) => s.model),
    workerModels: config.workers,
    discovery: [],
  });
  const council = new Council({ realm, config, brain: new SimBrain({ speed: 200, rand: seededRandom(seed) }) });
  council.seedAgents();
  const messages: ServerMessage[] = [];
  realm.on('message', (m) => messages.push(m));
  return { realm, council, messages };
}

test('config defaults and seeded agents', () => {
  const { realm, council } = setup('a');
  const agents = [...realm.agents.values()];
  assert.equal(agents.filter((a) => a.role === 'council').length, 3);
  assert.equal(agents.filter((a) => a.role === 'worker').length, 4);
  assert.equal(realm.getAgent('api:council-0')?.title, 'High Architect');
  assert.equal(realm.getAgent('api:council-0')?.skin.hat, 'crown');
  assert.ok(agents.every((a) => a.controllable && a.source === 'api' && !a.live));
  council.dispose();
  realm.dispose();
});

test('simulated mission runs the full state machine to complete', async () => {
  for (const seed of ['one', 'two', 'three']) {
    const { realm, council, messages } = setup(seed);
    const mission = council.summon('Build a habit tracker app');
    assert.equal(mission.simulated, true);
    const done = await council.waitFor(mission.id, 4000);
    assert.equal(done.status, 'complete', done.error ?? 'mission did not complete');

    const statuses = messages.filter((m) => m.type === 'mission').map((m) => (m.type === 'mission' ? m.mission.status : ''));
    for (const s of ['deliberating', 'planning', 'executing', 'reviewing', 'complete']) assert.ok(statuses.includes(s as never), `saw ${s}`);

    const phases = done.transcript.map((c) => c.phase);
    assert.equal(phases.filter((p) => p === 'proposal').length, 3);
    assert.ok(phases.includes('synthesis') && phases.includes('verdict') && phases.includes('review'));
    assert.ok(done.transcript.find((c) => c.phase === 'proposal')!.text.startsWith(SIM_BANNER));

    assert.ok(done.taskIds.length >= 4 && done.taskIds.length <= 8);
    for (const id of done.taskIds) {
      const t = realm.tasks.get(id)!;
      assert.equal(t.status, 'done');
      assert.ok(t.output?.includes(SIM_BANNER));
      assert.ok(t.attempts >= 1 && t.attempts <= 2);
      // dependencies finished before dependents
      for (const d of t.dependsOn) assert.equal(realm.tasks.get(d)?.status, 'done');
    }
    assert.ok(messages.some((m) => m.type === 'delegate'));
    assert.ok(messages.some((m) => m.type === 'deliver'));
    assert.ok(messages.some((m) => m.type === 'activity' && m.activity.kind === 'think'));
    const workersDone = [...realm.agents.values()].reduce((n, a) => n + a.stats.tasksDone, 0);
    assert.equal(workersDone, done.taskIds.length);
    council.dispose();
    realm.dispose();
  }
});

test('cancel_mission stops a running mission', async () => {
  const { realm, council } = setup('cancel');
  const mission = council.summon('Write a CLI');
  await new Promise((r) => setTimeout(r, 30));
  council.cancel(mission.id);
  const m = await council.waitFor(mission.id, 1000);
  assert.equal(m.status, 'cancelled');
  await new Promise((r) => setTimeout(r, 50));
  assert.equal(realm.missions.get(mission.id)?.status, 'cancelled');
  council.dispose();
  realm.dispose();
});

test('pushActivity caps recent history and counts tool calls', () => {
  const { realm, council } = setup('x');
  for (let i = 0; i < 60; i++) realm.pushActivity('api:worker-0', { kind: 'bash', text: `step ${i}` });
  const agent = realm.getAgent('api:worker-0')!;
  assert.equal(agent.recent.length, 40);
  assert.equal(agent.recent.at(-1)!.text, 'step 59');
  assert.equal(agent.stats.toolCalls, 60);
  assert.equal(agent.currentAction, 'step 59');
  council.dispose();
  realm.dispose();
});

test('failed task fails the mission; retry_task resumes it to completion', async () => {
  class FlakyBrain extends SimBrain {
    failures = 1;
    override async execute(...args: Parameters<SimBrain['execute']>) {
      if (this.failures-- > 0) throw new Error('boom');
      return super.execute(...args);
    }
  }
  const config = loadConfig('/nonexistent', {});
  const realm = new Realm({ version: 't', platform: 'linux', hostname: 't', apiKeyPresent: false, demoPopulation: false, councilModels: [], workerModels: [], discovery: [] });
  const council = new Council({ realm, config, brain: new FlakyBrain({ speed: 200, rand: seededRandom('flaky') }) });
  council.seedAgents();
  const mission = council.summon('Plan a garden');
  const failed = await council.waitFor(mission.id, 4000);
  assert.equal(failed.status, 'failed');
  const bad = failed.taskIds.map((id) => realm.tasks.get(id)!).find((t) => t.status === 'failed')!;
  assert.ok(bad);
  council.retryTask(bad.id);
  assert.equal(realm.missions.get(mission.id)?.status, 'executing');
  const done = await council.waitFor(mission.id, 4000);
  assert.equal(done.status, 'complete');
  council.dispose();
  realm.dispose();
});

test('assign_task to an observed (non-controllable) agent prepares a hand-off', async () => {
  const { realm, council } = setup('handoff');
  realm.upsertAgent({ ...realm.getAgent('api:worker-0')!, id: 'claude-code:abc', source: 'claude-code', controllable: false, live: true, recent: [] });
  const mission = council.summon('Write docs');
  // Wait until tasks exist, then hand the first backlog task to the observed agent.
  await new Promise<void>((resolve) => {
    const check = (): void => {
      const m = realm.missions.get(mission.id);
      if (m && m.taskIds.length) return resolve();
      setTimeout(check, 5);
    };
    check();
  });
  const m = realm.missions.get(mission.id)!;
  const backlog = m.taskIds.map((id) => realm.tasks.get(id)!).find((t) => t.status === 'backlog')!;
  council.assignTask(backlog.id, 'claude-code:abc');
  assert.equal(realm.tasks.get(backlog.id)?.status, 'assigned');
  const agent = realm.getAgent('claude-code:abc')!;
  assert.equal(agent.currentTaskId, backlog.id);
  assert.equal(agent.recent.at(-1)?.text, 'Instructions ready — hand off');
  council.cancel(mission.id);
  council.dispose();
  realm.dispose();
});
