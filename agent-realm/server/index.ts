import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { WebSocketServer, WebSocket } from 'ws';
import { DEFAULT_PORT, type ClientMessage, type ServerMessage } from '../shared/protocol.ts';
import { loadConfig, OverrideStore, PROJECT_ROOT } from './config.ts';
import { Council } from './council.ts';
import { DemoPopulation } from './demo.ts';
import { Discovery } from './discovery/index.ts';
import { parseClientMessage } from './schema.ts';
import { Realm } from './state.ts';
import { serveStatic } from './static.ts';

const VERSION = '0.1.0';

interface Args {
  host: string;
  port: number;
  open: boolean;
  demo?: boolean;
}

function parseArgs(argv: string[]): Args {
  const args: Args = { host: '127.0.0.1', port: Number(process.env.REALM_PORT ?? DEFAULT_PORT), open: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--host') args.host = argv[++i] ?? args.host;
    else if (a === '--port') args.port = Number(argv[++i] ?? args.port);
    else if (a === '--open') args.open = true;
    else if (a === '--demo') args.demo = true;
    else if (a === '--no-demo') args.demo = false;
  }
  if (!Number.isInteger(args.port) || args.port <= 0 || args.port > 65535) args.port = DEFAULT_PORT;
  return args;
}

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1', '[::1]']);
const isLoopback = (host: string): boolean => LOOPBACK_HOSTS.has(host) || host.startsWith('127.');

function hostnameOf(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    return new URL(value.includes('://') ? value : `http://${value}`).hostname.replace(/^\[|\]$/g, '');
  } catch {
    return undefined;
  }
}

const args = parseArgs(process.argv.slice(2));
const loopbackOnly = isLoopback(args.host);
const token = loopbackOnly ? undefined : randomBytes(18).toString('base64url');

function tokenOk(req: http.IncomingMessage): boolean {
  if (!token) return true;
  const url = new URL(req.url ?? '/', 'http://localhost');
  const given = url.searchParams.get('token') ?? String(req.headers['x-realm-token'] ?? '');
  const a = Buffer.from(given);
  const b = Buffer.from(token);
  return a.length === b.length && timingSafeEqual(a, b);
}

/**
 * In loopback mode, reject requests whose Host/Origin is not local: this blocks DNS-rebinding
 * and cross-site WebSocket hijacking from arbitrary web pages.
 */
function originOk(req: http.IncomingMessage): boolean {
  if (!loopbackOnly) return true;
  const host = hostnameOf(req.headers.host);
  if (host && !isLoopback(host)) return false;
  const origin = req.headers.origin;
  if (!origin) return true;
  const oh = hostnameOf(origin);
  return !!oh && isLoopback(oh);
}

// ── realm setup ─────────────────────────────────────────────────────────────

const config = loadConfig();
const overrides = new OverrideStore();
const realm = new Realm({
  version: VERSION,
  platform: process.platform,
  hostname: os.hostname(),
  apiKeyPresent: config.apiKeyPresent,
  demoPopulation: false,
  councilModels: config.council.map((s) => s.model),
  workerModels: config.workers,
  discovery: [],
});
const council = new Council({ realm, config, overrides, simSpeed: Number(process.env.REALM_SIM_SPEED) || 1 });
council.seedAgents();
const demo = new DemoPopulation(realm, overrides);
const discovery = new Discovery(realm, overrides);

function handle(msg: ClientMessage): void {
  switch (msg.type) {
    case 'summon_council':
      council.summon(msg.goal);
      break;
    case 'cancel_mission':
      council.cancel(msg.missionId);
      break;
    case 'set_role':
      council.setRole(msg.agentId, msg.role);
      break;
    case 'assign_task':
      council.assignTask(msg.taskId, msg.agentId);
      break;
    case 'complete_task':
      council.completeTask(msg.taskId, msg.note);
      break;
    case 'retry_task':
      council.retryTask(msg.taskId);
      break;
    case 'set_demo':
      demo.setEnabled(msg.enabled);
      break;
    case 'rename_agent':
      council.rename(msg.agentId, msg.name);
      break;
    case 'ping':
      break;
  }
}

// ── HTTP ────────────────────────────────────────────────────────────────────

const distDir = path.join(PROJECT_ROOT, 'dist');

function json(res: http.ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
  res.end(JSON.stringify(body));
}

const server = http.createServer((req, res) => {
  if (!originOk(req)) return json(res, 403, { error: 'forbidden host' });
  const url = new URL(req.url ?? '/', 'http://localhost');
  if (url.pathname.startsWith('/api/')) {
    if (!tokenOk(req)) return json(res, 401, { error: 'missing or invalid token' });
    if (req.method !== 'GET' && req.method !== 'HEAD') return json(res, 405, { error: 'method not allowed' });
    if (url.pathname === '/api/health') {
      return json(res, 200, { ok: true, version: VERSION, uptimeSec: Math.round(process.uptime()), clients: wss.clients.size });
    }
    if (url.pathname === '/api/snapshot') return json(res, 200, realm.snapshot());
    return json(res, 404, { error: 'not found' });
  }
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405).end();
    return;
  }
  serveStatic(distDir, req, res);
});

// ── WebSocket ───────────────────────────────────────────────────────────────

const wss = new WebSocketServer({ noServer: true, maxPayload: 64 * 1024 });
const alive = new WeakMap<WebSocket, boolean>();

server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url ?? '/', 'http://localhost');
  if (url.pathname !== '/ws' || !originOk(req) || !tokenOk(req)) {
    socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
    socket.destroy();
    return;
  }
  wss.handleUpgrade(req, socket, head, (ws) => wss.emit('connection', ws, req));
});

wss.on('connection', (ws) => {
  alive.set(ws, true);
  ws.on('pong', () => alive.set(ws, true));
  const hello: ServerMessage = { type: 'snapshot', data: realm.snapshot() };
  ws.send(JSON.stringify(hello));
  ws.on('message', (data, isBinary) => {
    if (isBinary) return;
    const msg = parseClientMessage(data.toString());
    if (!msg) return;
    try {
      handle(msg);
    } catch (err) {
      realm.toast('error', `Command failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  });
  ws.on('error', () => ws.terminate());
});

realm.on('message', (msg) => {
  if (!wss.clients.size) return;
  const payload = JSON.stringify(msg);
  for (const client of wss.clients) if (client.readyState === WebSocket.OPEN) client.send(payload);
});

const heartbeat = setInterval(() => {
  for (const ws of wss.clients) {
    if (!alive.get(ws)) {
      ws.terminate();
      continue;
    }
    alive.set(ws, false);
    ws.ping();
  }
}, 30_000);
heartbeat.unref();

// ── startup & shutdown ──────────────────────────────────────────────────────

function banner(url: string): void {
  const c = (code: number, s: string): string => (process.stdout.isTTY ? `\x1b[${code}m${s}\x1b[0m` : s);
  const sources = realm.info.discovery
    .map((d) => `${d.ok ? c(32, '●') : c(90, '○')} ${d.source}${d.ok ? ` (${d.count})` : d.note ? ` — ${d.note}` : ''}`)
    .join('\n            ');
  const lines = [
    '',
    c(1, '  ⛏  Agent Realm') + c(90, `  v${VERSION}`),
    '',
    `  ${c(90, 'URL')}       ${c(36, url)}`,
    `  ${c(90, 'Mode')}      ${loopbackOnly ? 'local only (loopback)' : c(33, `LAN (${args.host}) — token required`)}`,
    `  ${c(90, 'Council')}   ${config.apiKeyPresent ? c(32, 'Claude API key found — real deliberation') : c(33, 'no API key — simulated missions')}`,
    `  ${c(90, 'Models')}    council ${config.council.map((s) => s.model).join(', ')}`,
    `            workers ${config.workers.join(', ')}`,
    `  ${c(90, 'Demo')}      ${demo.isEnabled ? 'on (no live agents detected)' : 'off'}`,
    `  ${c(90, 'Sources')}   ${sources || 'scanning…'}`,
    '',
  ];
  console.log(lines.join('\n'));
}

server.on('error', (err: NodeJS.ErrnoException) => {
  console.error(err.code === 'EADDRINUSE' ? `Port ${args.port} is already in use (set REALM_PORT or --port).` : `Server error: ${err.message}`);
  process.exit(1);
});

server.listen(args.port, args.host, async () => {
  const displayHost = loopbackOnly ? '127.0.0.1' : args.host === '0.0.0.0' ? (lanAddress() ?? args.host) : args.host;
  const url = `http://${displayHost.includes(':') ? `[${displayHost}]` : displayHost}:${args.port}/${token ? `?token=${token}` : ''}`;
  try {
    await discovery.start();
  } catch {
    // Scanners report their own failures via RealmInfo.discovery.
  }
  demo.setEnabled(args.demo ?? discovery.liveCount() === 0);
  banner(url);
  if (args.open) {
    try {
      const { default: open } = await import('open');
      await open(url);
    } catch {
      console.log('  (could not open a browser automatically)');
    }
  }
});

function lanAddress(): string | undefined {
  for (const list of Object.values(os.networkInterfaces())) {
    for (const addr of list ?? []) if (addr.family === 'IPv4' && !addr.internal) return addr.address;
  }
  return undefined;
}

let shuttingDown = false;
function shutdown(): void {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log('\n  Closing the realm…');
  discovery.stop();
  demo.dispose();
  council.dispose();
  realm.dispose();
  overrides.flush();
  for (const ws of wss.clients) ws.close(1001, 'server shutting down');
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 1500).unref();
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
