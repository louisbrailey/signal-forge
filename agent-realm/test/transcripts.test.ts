import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ClaudeCodeScanner, describeToolUse, toolKind, transcriptEntryToActivities, transcriptMeta } from '../server/discovery/claudeCode.ts';
import { codexEntryToActivities } from '../server/discovery/codex.ts';

const cwd = '/home/me/proj';
const ts = '2026-09-24T10:00:00.000Z';

function assistant(content: unknown[], extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    type: 'assistant',
    sessionId: 's1',
    cwd,
    timestamp: ts,
    gitBranch: 'main',
    message: { id: 'msg_1', model: 'claude-opus-5', content, usage: { input_tokens: 100, output_tokens: 20 } },
    ...extra,
  };
}

test('tool names map to activity kinds', () => {
  assert.equal(toolKind('Read'), 'read');
  assert.equal(toolKind('Grep'), 'search');
  assert.equal(toolKind('Glob'), 'search');
  assert.equal(toolKind('Edit'), 'edit');
  assert.equal(toolKind('MultiEdit'), 'edit');
  assert.equal(toolKind('NotebookEdit'), 'edit');
  assert.equal(toolKind('Bash'), 'bash');
  assert.equal(toolKind('WebSearch'), 'web');
  assert.equal(toolKind('Task'), 'delegate');
  assert.equal(toolKind('Agent'), 'delegate');
  assert.equal(toolKind('TodoWrite'), 'plan');
  assert.equal(toolKind('mcp__github__get_me'), 'tool');
});

test('tool_use blocks become readable activities with relative paths', () => {
  const acts = transcriptEntryToActivities(
    assistant([
      { type: 'tool_use', name: 'Edit', input: { file_path: '/home/me/proj/src/app.ts', old_string: 'a', new_string: 'b' } },
      { type: 'tool_use', name: 'Bash', input: { command: 'npm test\necho done' } },
      { type: 'tool_use', name: 'Grep', input: { pattern: 'foo' } },
      { type: 'tool_use', name: 'Read', input: { file_path: '/home/me/proj/README.md' } },
      { type: 'text', text: '\nAll tests pass now.\nSecond line' },
      { type: 'thinking', thinking: '' },
    ]),
  );
  assert.deepEqual(
    acts.map((a) => [a.kind, a.text]),
    [
      ['edit', 'Edit src/app.ts'],
      ['bash', 'Bash: npm test'],
      ['search', "Grep 'foo'"],
      ['read', 'Read README.md'],
      ['message', 'All tests pass now.'],
      ['think', 'Thinking…'],
    ],
  );
  assert.equal(acts[0]!.ts, Date.parse(ts));
});

test('long paths outside cwd collapse to basename', () => {
  assert.equal(describeToolUse('Read', { file_path: '/very/long/path/that/goes/on/and/on/forever/and/ever/deeply/file.ts' }, cwd), 'Read file.ts');
  assert.equal(describeToolUse('Write', { file_path: '/etc/hosts' }, cwd), 'Write /etc/hosts');
});

test('user entries: prompts and tool errors; unknown shapes never throw', () => {
  const prompt = transcriptEntryToActivities({ type: 'user', timestamp: ts, message: { role: 'user', content: 'Please fix the build' } });
  assert.deepEqual(prompt.map((a) => a.kind), ['message']);
  const err = transcriptEntryToActivities({
    type: 'user',
    timestamp: ts,
    message: { content: [{ type: 'tool_result', is_error: true, content: 'Exit code 1' }, { type: 'tool_result', content: 'ok' }] },
  });
  assert.deepEqual(err.map((a) => [a.kind, a.text]), [['error', 'Tool error: Exit code 1']]);
  for (const junk of [null, 42, 'str', [], {}, { type: 'assistant' }, { type: 'assistant', message: { content: 'x' } }, { type: 'assistant', message: { content: [null, 1, { type: 'tool_use' }] } }]) {
    assert.doesNotThrow(() => transcriptEntryToActivities(junk));
    assert.doesNotThrow(() => transcriptMeta(junk));
  }
});

test('transcriptMeta extracts session, model and usage', () => {
  const meta = transcriptMeta(assistant([]));
  assert.equal(meta.sessionId, 's1');
  assert.equal(meta.model, 'claude-opus-5');
  assert.equal(meta.cwd, cwd);
  assert.deepEqual(meta.usage, { requestKey: 'msg_1', input: 100, output: 20 });
});

test('ClaudeCodeScanner tails files incrementally and dedupes usage', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'realm-cc-'));
  const dir = path.join(root, '-home-me-proj');
  fs.mkdirSync(dir);
  const file = path.join(dir, 's1.jsonl');
  const now = Date.now();
  const stamp = new Date(now - 1000).toISOString();
  const line = (content: unknown[]): string => JSON.stringify(assistant(content, { timestamp: stamp })) + '\n';
  fs.writeFileSync(file, line([{ type: 'tool_use', name: 'Read', input: { file_path: `${cwd}/a.ts` } }]) + line([{ type: 'text', text: 'hi' }]));
  const scanner = new ClaudeCodeScanner(root);
  const first = await scanner.scan(now);
  assert.equal(first.length, 1);
  assert.equal(first[0]!.id, 'claude-code:s1');
  assert.equal(first[0]!.status, 'working');
  assert.equal(first[0]!.activities.length, 2);
  assert.equal(first[0]!.tokensIn, 100, 'same message id counted once');
  fs.appendFileSync(file, line([{ type: 'tool_use', name: 'Bash', input: { command: 'ls' } }]));
  const second = await scanner.scan(now);
  assert.deepEqual(second[0]!.activities.map((a) => a.text), ['Bash: ls']);
  const third = await scanner.scan(now + 25_000);
  assert.equal(third[0]!.status, 'idle');
  assert.equal(third[0]!.activities.length, 0);
  fs.rmSync(root, { recursive: true, force: true });
});

test('codex rollout entries map to activities', () => {
  const shell = codexEntryToActivities({ timestamp: ts, type: 'response_item', payload: { type: 'function_call', name: 'shell', arguments: '{"command":["bash","-lc","npm test"]}' } });
  assert.deepEqual(shell.map((a) => [a.kind, a.text]), [['bash', 'Bash: npm test']]);
  const patch = codexEntryToActivities(
    { timestamp: ts, type: 'response_item', payload: { type: 'custom_tool_call', name: 'apply_patch', input: '*** Begin Patch\n*** Update File: /home/me/proj/src/x.ts\n' } },
    cwd,
  );
  assert.deepEqual(patch.map((a) => a.text), ['Edit src/x.ts']);
  const msg = codexEntryToActivities({ timestamp: ts, type: 'response_item', payload: { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Done.' }] } });
  assert.equal(msg[0]!.kind, 'message');
  assert.deepEqual(codexEntryToActivities({ type: 'event_msg', payload: { type: 'token_count' } }), []);
  assert.doesNotThrow(() => codexEntryToActivities({ type: 'response_item', payload: { type: 'function_call', arguments: '{bad' } }));
});
