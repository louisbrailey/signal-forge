import fs from 'node:fs/promises';

const FIRST_READ_BYTES = 256 * 1024;
const MAX_READ_BYTES = 4 * 1024 * 1024;

interface FileCursor {
  offset: number;
  leftover: string;
}

export interface TailResult {
  lines: unknown[];
  /** True the first time a file is seen (lines are a backfill of recent history). */
  firstRead: boolean;
}

/** Incremental JSONL reader: tracks a byte offset per file and returns only new, parsed lines. */
export class JsonlTailer {
  private cursors = new Map<string, FileCursor>();

  async read(file: string, size: number): Promise<TailResult> {
    let cursor = this.cursors.get(file);
    const firstRead = !cursor;
    if (!cursor || size < cursor.offset) {
      // New file, or truncated/rotated: start near the end.
      const start = Math.max(0, size - FIRST_READ_BYTES);
      cursor = { offset: start, leftover: '' };
      this.cursors.set(file, cursor);
      if (start > 0) cursor.leftover = '\u0000skip';
    }
    if (size === cursor.offset) return { lines: [], firstRead };

    const length = Math.min(size - cursor.offset, MAX_READ_BYTES);
    const start = size - cursor.offset > MAX_READ_BYTES ? size - MAX_READ_BYTES : cursor.offset;
    if (start !== cursor.offset) cursor.leftover = '\u0000skip';
    const handle = await fs.open(file, 'r');
    let chunk: string;
    try {
      const buf = Buffer.alloc(length);
      const { bytesRead } = await handle.read(buf, 0, length, start);
      chunk = buf.subarray(0, bytesRead).toString('utf8');
      cursor.offset = start + bytesRead;
    } finally {
      await handle.close();
    }

    let text = cursor.leftover + chunk;
    if (cursor.leftover.startsWith('\u0000skip')) {
      // We started mid-file: drop the partial first line.
      const nl = chunk.indexOf('\n');
      text = nl === -1 ? '' : chunk.slice(nl + 1);
    }
    const parts = text.split('\n');
    cursor.leftover = parts.pop() ?? '';
    const lines: unknown[] = [];
    for (const part of parts) {
      const trimmed = part.trim();
      if (!trimmed) continue;
      try {
        lines.push(JSON.parse(trimmed));
      } catch {
        // Corrupt or partial line: skip.
      }
    }
    return { lines, firstRead };
  }

  forget(keep: Set<string>): void {
    for (const file of this.cursors.keys()) if (!keep.has(file)) this.cursors.delete(file);
  }
}
