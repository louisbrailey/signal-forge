import fs from 'node:fs';
import path from 'node:path';
import type { IncomingMessage, ServerResponse } from 'node:http';

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.wasm': 'application/wasm',
  '.txt': 'text/plain; charset=utf-8',
  '.glb': 'model/gltf-binary',
  '.ogg': 'audio/ogg',
  '.mp3': 'audio/mpeg',
};

const NOT_BUILT = `<!doctype html><meta charset="utf-8"><title>Agent Realm</title>
<body style="font-family:system-ui;background:#1b1d23;color:#e8e6e3;padding:40px">
<h1>Agent Realm server is running</h1>
<p>The client has not been built yet. Run <code>npm run build</code> (then reload), or use <code>npm run dev</code> and open <a style="color:#8cc4ff" href="http://localhost:5173">http://localhost:5173</a>.</p>
<p>API: <a style="color:#8cc4ff" href="/api/health">/api/health</a></p></body>`;

/** Serve files from `root` with SPA fallback to index.html. Returns false if nothing was served. */
export function serveStatic(root: string, req: IncomingMessage, res: ServerResponse): void {
  const url = new URL(req.url ?? '/', 'http://localhost');
  let rel: string;
  try {
    rel = decodeURIComponent(url.pathname);
  } catch {
    res.writeHead(400).end('Bad request');
    return;
  }
  const resolved = path.resolve(root, '.' + path.posix.normalize('/' + rel));
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    res.writeHead(403).end('Forbidden');
    return;
  }
  let file = resolved;
  try {
    if (fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
  } catch {
    // Unknown path: SPA fallback for route-like URLs, 404 for missing assets.
    file = path.extname(resolved) ? '' : path.join(root, 'index.html');
  }
  if (!file || !fs.existsSync(file)) {
    if (!fs.existsSync(path.join(root, 'index.html'))) {
      res.writeHead(200, { 'content-type': MIME['.html']! }).end(NOT_BUILT);
    } else {
      res.writeHead(404, { 'content-type': 'text/plain' }).end('Not found');
    }
    return;
  }
  const ext = path.extname(file).toLowerCase();
  const immutable = file.includes(`${path.sep}assets${path.sep}`);
  res.writeHead(200, {
    'content-type': MIME[ext] ?? 'application/octet-stream',
    'cache-control': immutable ? 'public, max-age=31536000, immutable' : 'no-cache',
    'x-content-type-options': 'nosniff',
  });
  if (req.method === 'HEAD') {
    res.end();
    return;
  }
  fs.createReadStream(file).pipe(res);
}
