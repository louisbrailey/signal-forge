import { z } from 'zod';
import type { ClientMessage } from '../shared/protocol.ts';

const id = z.string().min(1).max(200);

export const clientMessageSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('summon_council'), goal: z.string().trim().min(1).max(4000) }),
  z.object({ type: z.literal('cancel_mission'), missionId: id }),
  z.object({ type: z.literal('set_role'), agentId: id, role: z.enum(['council', 'worker']) }),
  z.object({ type: z.literal('assign_task'), taskId: id, agentId: id }),
  z.object({ type: z.literal('retry_task'), taskId: id }),
  z.object({ type: z.literal('set_demo'), enabled: z.boolean() }),
  z.object({ type: z.literal('rename_agent'), agentId: id, name: z.string().trim().min(1).max(64) }),
  z.object({ type: z.literal('ping') }),
]);

// Compile-time check that the schema and the protocol type agree.
type Parsed = z.infer<typeof clientMessageSchema>;
const _check: [Parsed] extends [ClientMessage] ? ([ClientMessage] extends [Parsed] ? true : false) : false = true;
void _check;

export function parseClientMessage(raw: string): ClientMessage | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  const result = clientMessageSchema.safeParse(data);
  return result.success ? result.data : null;
}
