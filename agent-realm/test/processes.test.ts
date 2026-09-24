import { test } from 'node:test';
import assert from 'node:assert/strict';
import { collapseMatches, matchSignature, parseEtime, parsePsLine, parsePsOutput, parseWindowsJson, stripSecrets, type RawProcess } from '../server/discovery/processes.ts';

test('parseEtime handles all ps formats', () => {
  assert.equal(parseEtime('00:05'), 5);
  assert.equal(parseEtime('12:34'), 12 * 60 + 34);
  assert.equal(parseEtime('01:02:03'), 3723);
  assert.equal(parseEtime('2-01:02:03'), 2 * 86400 + 3723);
  assert.equal(parseEtime('garbage'), undefined);
});

test('parsePsLine parses pid/ppid/cpu/rss/etime/args', () => {
  const now = 1_000_000_000;
  const p = parsePsLine('  4242     1  12.5  204800   01:00 node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js --resume', now);
  assert.ok(p);
  assert.equal(p.pid, 4242);
  assert.equal(p.ppid, 1);
  assert.equal(p.cpu, 12.5);
  assert.equal(p.rssKb, 204800);
  assert.equal(p.startedAt, now - 60_000);
  assert.equal(p.args, 'node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js --resume');
  assert.equal(parsePsLine('not a process line'), undefined);
  assert.equal(parsePsOutput('1 0 0.0 100 00:01 init\n\n2 1 0.0 100 00:01 bash\n').length, 2);
});

test('parseWindowsJson reads CIM output, single object or array', () => {
  const one = parseWindowsJson('{"ProcessId":10,"ParentProcessId":4,"CommandLine":"codex.exe","WorkingSetSize":2097152,"CreationDate":"/Date(1700000000000)/"}');
  assert.equal(one.length, 1);
  assert.equal(one[0]!.rssKb, 2048);
  assert.equal(one[0]!.startedAt, 1700000000000);
  assert.equal(parseWindowsJson('[{"ProcessId":1},{"nope":true}]').length, 1);
  assert.deepEqual(parseWindowsJson('not json'), []);
});

test('matchSignature recognises agent CLIs', () => {
  const cases: Array<[string, string | null]> = [
    ['node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js', 'claude-code'],
    ['/Users/me/.local/bin/claude --dangerously-skip-permissions', 'claude-code'],
    ['claude', 'claude-code'],
    ['node /opt/homebrew/bin/codex', 'codex'],
    ['/usr/local/bin/codex exec "fix"', 'codex'],
    ['node /usr/lib/node_modules/@google/gemini-cli/dist/index.js', 'gemini-cli'],
    ['/usr/bin/python3 /home/me/.local/bin/aider --model sonnet', 'aider'],
    ['python -m aider', 'aider'],
    ['/usr/local/bin/ollama serve', 'ollama'],
    ['ollama run llama3', 'ollama'],
    ['cursor-agent chat', 'cursor'],
    ['node /usr/lib/node_modules/@github/copilot/index.js', 'copilot'],
    ['/home/me/.opencode/bin/opencode', 'opencode'],
    ['/usr/local/bin/goose session', 'goose'],
    ['/Applications/Cursor.app/Contents/MacOS/Cursor', 'cursor'],
    ['/Applications/Claude.app/Contents/MacOS/Claude', 'other'],
    ['/Applications/Claude.app/Contents/Frameworks/Claude Helper (Renderer).app/Contents/MacOS/Claude Helper (Renderer) --type=renderer', null],
    ['/Applications/Cursor.app/Contents/Frameworks/Cursor Helper.app/Contents/MacOS/Cursor Helper --type=gpu-process', null],
    ['ollama list', null],
    ['vim claude.md', null],
    ['/bin/zsh -l', null],
    ['node server.js', null],
  ];
  for (const [cmd, expected] of cases) {
    assert.equal(matchSignature(cmd)?.source ?? null, expected, cmd);
  }
  assert.equal(matchSignature('/Applications/Claude.app/Contents/MacOS/Claude')?.label, 'Claude Desktop');
});

test('collapseMatches folds child agent processes into the top-most match and sums the subtree', () => {
  const procs: RawProcess[] = [
    { pid: 1, ppid: 0, cpu: 0, rssKb: 100, args: '/sbin/init' },
    { pid: 10, ppid: 1, cpu: 1, rssKb: 1000, args: '/bin/zsh' },
    { pid: 20, ppid: 10, cpu: 5, rssKb: 2000, args: 'node /x/@anthropic-ai/claude-code/cli.js' },
    { pid: 21, ppid: 20, cpu: 10, rssKb: 3000, args: 'claude --print sub' },
    { pid: 22, ppid: 20, cpu: 20, rssKb: 4000, args: 'npm test' },
    { pid: 30, ppid: 10, cpu: 2, rssKb: 500, args: 'codex' },
  ];
  const roots = collapseMatches(procs);
  assert.equal(roots.length, 2);
  const claude = roots.find((r) => r.signature.source === 'claude-code')!;
  assert.equal(claude.root.pid, 20);
  assert.equal(claude.cpu, 35);
  assert.equal(claude.rssKb, 9000);
});

test('stripSecrets redacts keys and tokens and truncates', () => {
  const out = stripSecrets('aider --api-key sk-ant-abc123456789 --openai-api-key=xyz ANTHROPIC_API_KEY=secret123 --token "a b" ghp_abcdefghijklmnop https://user:pass@host/x');
  assert.ok(!out.includes('sk-ant-abc123456789'), out);
  assert.ok(!out.includes('xyz'), out);
  assert.ok(!out.includes('secret123'), out);
  assert.ok(!out.includes('ghp_abcdefghijklmnop'), out);
  assert.ok(!out.includes('pass@'), out);
  assert.ok(out.includes('--api-key'));
  assert.equal(stripSecrets('x'.repeat(500)).length, 200);
  assert.equal(stripSecrets('claude --model opus'), 'claude --model opus');
});
