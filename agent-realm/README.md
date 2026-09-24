# Agent Realm

Every AI agent running on your computer shows up as a villager in a Minecraft-style voxel world. **Workers** build at their plots, and a **council** of the most capable Claude models plans the work in the Council Hall and hands it out.

- **See what each agent is doing.** Claude Code, Codex CLI, Gemini CLI, Aider, Cursor, Copilot CLI, opencode, Goose and Ollama are found automatically. Every file read, edit and command appears as a speech bubble, a particle effect, or a block added to that agent's build site.
- **Council and workers.** Give the council a goal. Three council models each propose an approach, the chair writes one plan (architecture, principles, milestones, task briefs), and the tasks go to worker models. The Warden reviews each result before it's accepted.
- **Click a villager** to see its model, project, working directory, CPU and memory use, a live activity log, and token counts.
- **Installable.** It runs locally on macOS, Windows and Linux, and can be installed as a desktop app (PWA) from Chrome, Edge or Safari.

## Quick start

Requires Node.js 20 or newer.

```bash
cd agent-realm
npm install
npm start            # builds the client, starts the server, opens http://127.0.0.1:4777
```

To run real council deliberation and worker execution, set a Claude API key before starting:

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
npm start
```

Without a key everything still works, but missions run as a **simulation**. Every simulated output is labelled as such.

**Install as an app.** Open the realm in Chrome or Edge and use *Install Agent Realm* in the address bar; in Safari use *File → Add to Dock*. The realm then opens in its own window from the Dock, Start menu or Spotlight. The server still has to be running (see [Run at login](#run-at-login)).

### Development

```bash
npm run dev          # server (auto-restart) on :4777 + Vite client with hot reload on :5173
npm test             # server unit tests (no network)
npm run typecheck
```

Open `http://localhost:5173/world-preview.html` to preview the 3D world with fake agents and no server.

## Using it

| Key | Action |
| --- | --- |
| `T` or `/` | Open the command bar and give the council a goal |
| `1`–`9` | Jump to a villager in the hotbar |
| Click | Select a villager (in the world or in the list) |
| `F` | Follow / stop following the selected villager |
| `O` `C` `V` | Camera: overview, Council Hall, village |
| `M` | Council Chamber: missions, deliberation, framework, quest board |
| `N` | Cycle time of day: auto (your clock), day, night |
| `Tab` | Hide or show the villager list |
| `Esc` | Close panels / deselect |

**How a mission runs**

1. **Convene and deliberate.** Each council member writes a proposal: analysis, framework, risks and candidate tasks.
2. **Plan.** The chair combines the proposals into a single plan: a summary, an architecture, principles, milestones, and 3–8 tasks. Each task has self-contained instructions, acceptance criteria, dependencies and a suggested assignee.
3. **Execute.** Tasks whose dependencies are done go to idle workers: Sonnet for large tasks, Haiku for small ones. Workers stream their output, and you can watch progress on their plots and on the quest board.
4. **Review.** The Warden approves each deliverable or sends it back once with notes. The chair then writes a final verdict.

Detected agents can be given tasks too: reassign a task to one from the quest board. The realm **observes** these agents but does not control them. It prepares a hand-off brief (*Copy brief*), and you click *Mark done* when the agent has finished.

## Where the data comes from

| Source | How |
| --- | --- |
| Running processes | `ps` (macOS/Linux) or PowerShell `Get-CimInstance` (Windows), matched by command line. Child processes are grouped under their parent agent, and anything that looks like a secret is stripped from command lines. |
| Claude Code | New lines appended to `~/.claude/projects/*/*.jsonl` (sessions active in the last 30 min) |
| Codex CLI | New lines appended to `~/.codex/sessions/**/*.jsonl` |
| Ollama | `GET http://127.0.0.1:11434/api/ps` |

**Privacy.** The server listens on `127.0.0.1` only and rejects requests from other web pages. Transcript contents and process details never leave your machine. The council only ever receives your goal, the list of agents (names, models and status) and the workers' task outputs.

## Configuration

Create `realm.config.local.json` (git-ignored) in this folder, or use environment variables:

```json
{
  "councilModels": ["claude-fable-5-1", { "model": "claude-opus-5-5", "title": "Grand Strategist" }, "claude-opus-5"],
  "workerModels": ["claude-sonnet-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-haiku-4-5"]
}
```

| Setting | Default | Notes |
| --- | --- | --- |
| `REALM_COUNCIL_MODELS` | Fable 5.1 (High Architect, chair), Opus 5.5 (Grand Strategist), Opus 5 (Warden) | Comma-separated model IDs; the first is the chair and the last reviews results |
| `REALM_WORKER_MODELS` | 2× Sonnet 5, 2× Haiku 4.5 | One worker is created per entry |
| `REALM_PORT` / `--port` | `4777` | |
| `--host 0.0.0.0` | off | Makes the realm reachable from other devices on your network (e.g. a phone). Access requires the random token printed at startup. |
| `--demo` / `--no-demo` | on only if no agents are detected | Adds simulated citizens so the world isn't empty |
| `REALM_SIM_SPEED` | `1` | Speeds up simulated missions |

Role changes and renames are saved to `~/.agent-realm/overrides.json`. You can promote any villager, including a detected agent, to the council.

## Run at login

- **macOS:** create a Login Item or a `launchd` agent that runs `npm run serve` in this folder, then open the installed app.
- **Windows:** add a shortcut to `cmd /c "cd /d <path>\agent-realm && npm run serve"` in `shell:startup`.

## Architecture

```
shared/protocol.ts    WebSocket contract (types for every message)
server/               Node server (tsx) — no build step
  index.ts            HTTP + /ws, static client, CLI flags
  state.ts            realm store + broadcast
  discovery/          process, Claude Code, Codex, Ollama scanners
  council.ts          mission state machine + scheduler
  workers.ts          task execution + review loop
  brain.ts            Claude API prompts and JSON schemas (via claude.ts)
  simulation.ts       scripted brain used when there is no API key
  demo.ts             simulated citizens
src/                  browser client (Vite + TypeScript)
  world/              Three.js voxel world: terrain, Council Hall, village, villagers, effects
  ui/                 HUD: roster, inspector, hotbar, chat/command bar, quest log, Council Chamber
```

All textures, skins and models are generated in code. No Minecraft assets are used.
