// Shared contract between the realm server (server/) and the browser client (src/).
// Everything that crosses the WebSocket is defined here. Keep it serialisable (plain JSON).

export type AgentRole = 'council' | 'worker';

export type AgentStatus =
  | 'idle' // alive, nothing happening
  | 'thinking' // model is reasoning / deliberating
  | 'working' // actively using tools / producing output
  | 'waiting' // blocked on a dependency or on the user
  | 'done' // finished its current task
  | 'error'
  | 'offline'; // process ended; kept briefly so the world can show it leaving

/** Where an agent came from. Detected ones are real processes/sessions on this machine. */
export type AgentSource =
  | 'claude-code'
  | 'codex'
  | 'gemini-cli'
  | 'aider'
  | 'cursor'
  | 'ollama'
  | 'copilot'
  | 'opencode'
  | 'goose'
  | 'api' // a model the realm itself drives through the Claude API
  | 'demo' // simulated citizen (demo population)
  | 'other';

export type HatStyle = 'none' | 'crown' | 'wizard' | 'hood' | 'helmet' | 'cap' | 'headband';

/** Procedural Minecraft-style skin. All colours are CSS hex strings (#rrggbb). */
export interface SkinSpec {
  skin: string;
  hair: string;
  eyes: string;
  shirt: string;
  pants: string;
  shoes: string;
  accent: string; // trim / belt / robe edge
  hat: HatStyle;
  cape?: string; // council members wear capes
}

export type ActivityKind =
  | 'read'
  | 'edit'
  | 'bash'
  | 'search'
  | 'web'
  | 'tool'
  | 'think'
  | 'message'
  | 'plan'
  | 'delegate'
  | 'review'
  | 'complete'
  | 'error'
  | 'system';

export interface Activity {
  id: string;
  agentId: string;
  ts: number; // epoch ms
  kind: ActivityKind;
  text: string; // one short line, e.g. "Edit server/index.ts"
  detail?: string; // optional longer text (truncated server-side to ~2k chars)
  taskId?: string;
}

export interface ProcessInfo {
  pid: number;
  cpu: number; // percent
  memMb: number;
  startedAt?: number; // epoch ms, if known
  command: string; // truncated, never includes env
}

export interface AgentStats {
  toolCalls: number;
  tasksDone: number;
  tokensIn: number;
  tokensOut: number;
}

export interface Agent {
  id: string; // stable id, e.g. "claude-code:3f2a…" or "api:council-chair"
  name: string; // villager name, e.g. "Ember"
  title: string; // e.g. "High Architect", "Claude Code · signal-forge"
  role: AgentRole;
  source: AgentSource;
  model?: string; // model id or label when known
  status: AgentStatus;
  live: boolean; // true = real detected process/session or real API model; false = simulated
  controllable: boolean; // realm can assign & execute tasks on it (API-backed workers)
  skin: SkinSpec;
  process?: ProcessInfo;
  project?: string; // short project name (basename of cwd)
  cwd?: string;
  currentTaskId?: string;
  currentAction?: string; // short speech-bubble text
  lastActivityAt: number;
  createdAt: number;
  stats: AgentStats;
  recent: Activity[]; // newest last, capped (~40)
}

export type TaskStatus = 'backlog' | 'assigned' | 'in_progress' | 'review' | 'done' | 'failed' | 'blocked';
export type TaskPriority = 'low' | 'normal' | 'high' | 'critical';

export interface TaskReview {
  reviewerId: string;
  verdict: 'approved' | 'revise';
  notes: string;
}

export interface Task {
  id: string;
  missionId: string;
  title: string;
  goal: string;
  instructions: string;
  acceptance: string[];
  dependsOn: string[]; // task ids
  assigneeId?: string;
  status: TaskStatus;
  priority: TaskPriority;
  progress: number; // 0..1
  output?: string; // worker deliverable (markdown)
  review?: TaskReview;
  attempts: number;
  createdAt: number;
  updatedAt: number;
}

export type MissionStatus =
  | 'convening'
  | 'deliberating'
  | 'planning'
  | 'executing'
  | 'reviewing'
  | 'complete'
  | 'failed'
  | 'cancelled';

export interface CouncilContribution {
  id: string;
  memberId: string;
  phase: 'proposal' | 'synthesis' | 'review' | 'verdict';
  text: string; // markdown
  ts: number;
}

export interface MissionFramework {
  architecture: string;
  principles: string[];
  milestones: string[];
}

export interface Mission {
  id: string;
  goal: string;
  status: MissionStatus;
  simulated: boolean; // true when no API key: deliberation is scripted, not real model output
  createdAt: number;
  updatedAt: number;
  summary?: string;
  framework?: MissionFramework;
  taskIds: string[];
  transcript: CouncilContribution[];
  error?: string;
}

export interface DiscoveryStatus {
  source: string; // e.g. "processes", "claude-code transcripts", "ollama"
  ok: boolean;
  count: number;
  note?: string;
}

export interface RealmInfo {
  version: string;
  platform: string; // darwin | win32 | linux
  hostname: string;
  apiKeyPresent: boolean; // Claude API reachable for council/worker execution
  demoPopulation: boolean;
  councilModels: string[];
  workerModels: string[];
  discovery: DiscoveryStatus[];
}

export interface RealmSnapshot {
  info: RealmInfo;
  agents: Agent[];
  tasks: Task[];
  missions: Mission[];
  serverTime: number;
}

export type ToastLevel = 'info' | 'success' | 'warn' | 'error';

export type ServerMessage =
  | { type: 'snapshot'; data: RealmSnapshot }
  | { type: 'agent'; agent: Agent } // upsert (full object)
  | { type: 'agent_removed'; id: string }
  | { type: 'activity'; activity: Activity } // also appended to agent.recent server-side
  | { type: 'task'; task: Task } // upsert
  | { type: 'mission'; mission: Mission } // upsert
  | { type: 'delegate'; fromId: string; toId: string; taskId: string } // visual: scroll flies council → worker
  | { type: 'deliver'; fromId: string; toId: string; taskId: string } // visual: result flies worker → council
  | { type: 'toast'; level: ToastLevel; text: string }
  | { type: 'info'; info: RealmInfo };

export type ClientMessage =
  | { type: 'summon_council'; goal: string }
  | { type: 'cancel_mission'; missionId: string }
  | { type: 'set_role'; agentId: string; role: AgentRole }
  | { type: 'assign_task'; taskId: string; agentId: string }
  | { type: 'retry_task'; taskId: string }
  | { type: 'set_demo'; enabled: boolean }
  | { type: 'rename_agent'; agentId: string; name: string }
  | { type: 'ping' };

export const DEFAULT_PORT = 4777;
export const RECENT_ACTIVITY_CAP = 40;
