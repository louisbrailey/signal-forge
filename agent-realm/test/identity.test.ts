import { test } from 'node:test';
import assert from 'node:assert/strict';
import { modelLabel, nameFor, skinFor, titleFor } from '../server/identity.ts';

test('identity is deterministic per agent id', () => {
  assert.equal(nameFor('claude-code:abc'), nameFor('claude-code:abc'));
  const a = skinFor({ id: 'codex:1', source: 'codex', role: 'worker' });
  const b = skinFor({ id: 'codex:1', source: 'codex', role: 'worker' });
  assert.deepEqual(a, b);
  const names = new Set(Array.from({ length: 50 }, (_, i) => nameFor(`agent-${i}`)));
  assert.ok(names.size > 20, 'names should vary across ids');
});

test('skins follow source and role themes', () => {
  const hex = /^#[0-9a-f]{6}$/i;
  const worker = skinFor({ id: 'x', source: 'claude-code', role: 'worker' });
  for (const v of [worker.skin, worker.hair, worker.eyes, worker.shirt, worker.pants, worker.shoes, worker.accent]) assert.match(v, hex);
  assert.equal(worker.cape, undefined);
  const chair = skinFor({ id: 'api:council-0', source: 'api', role: 'council', chair: true });
  assert.equal(chair.hat, 'crown');
  assert.ok(chair.cape);
  assert.equal(skinFor({ id: 'api:council-1', source: 'api', role: 'council' }).hat, 'wizard');
  const sonnet = skinFor({ id: 'w', source: 'api', role: 'worker', model: 'claude-sonnet-5' });
  const haiku = skinFor({ id: 'w', source: 'api', role: 'worker', model: 'claude-haiku-4-5' });
  assert.notEqual(sonnet.shirt, haiku.shirt);
});

test('titles and model labels', () => {
  assert.equal(modelLabel('claude-sonnet-5'), 'Sonnet 5');
  assert.equal(modelLabel('claude-haiku-4-5'), 'Haiku 4.5');
  assert.equal(modelLabel('claude-fable-5-1'), 'Fable 5.1');
  assert.equal(modelLabel('llama3'), 'llama3');
  assert.equal(titleFor({ source: 'claude-code', role: 'worker', project: 'signal-forge', live: true }), 'Claude Code · signal-forge');
  assert.equal(titleFor({ source: 'api', role: 'worker', model: 'claude-haiku-4-5', live: true }), 'Haiku 4.5 · Worker');
  assert.match(titleFor({ source: 'codex', role: 'worker', project: 'web', live: false }), /demo/);
});
