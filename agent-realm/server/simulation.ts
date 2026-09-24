// Scripted, goal-aware stand-in for the Claude API, used when no API key is configured.
// Everything it writes is labelled as simulated.
import type { TaskPriority } from '../shared/protocol.ts';
import type {
  Brain,
  BrainCall,
  ExecuteInput,
  Gen,
  Plan,
  PlanTask,
  ProposeInput,
  Review,
  ReviewInput,
  RosterEntry,
  SynthesizeInput,
  VerdictInput,
} from './brain.ts';
import { sleep, truncate } from './util.ts';

export const SIM_BANNER = '_Simulated council — add ANTHROPIC_API_KEY for real deliberation._';

export interface SimOptions {
  /** Time compression factor: 1 = realistic pacing, 100 = 100× faster (tests). */
  speed?: number;
  rand?: () => number;
}

function shortGoal(goal: string): string {
  const clean = goal.replace(/\s+/g, ' ').trim().replace(/[.!?]+$/, '');
  const lower = clean.charAt(0).toLowerCase() + clean.slice(1);
  return truncate(lower, 48);
}

/** "Build a tiny weather dashboard" → "tiny weather dashboard", for task titles. */
function subject(goal: string): string {
  const g = shortGoal(goal);
  const stripped = g.replace(/^(?:please\s+)?(?:build|create|make|write|design|implement|develop|set up|add|ship)\s+(?:a|an|the|our|my)?\s*/i, '');
  return stripped || g;
}

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

export class SimBrain implements Brain {
  readonly simulated = true;
  private readonly speed: number;
  private readonly rand: () => number;

  constructor(opts: SimOptions = {}) {
    this.speed = Math.max(0.01, opts.speed ?? 1);
    this.rand = opts.rand ?? Math.random;
  }

  private between(minMs: number, maxMs: number): number {
    return (minMs + this.rand() * (maxMs - minMs)) / this.speed;
  }

  /** Emit text in word chunks spread over `durationMs`. */
  private async stream(call: BrainCall, text: string, durationMs: number): Promise<void> {
    const chunks = text.match(/\S+\s*/g) ?? [text];
    const steps = Math.min(chunks.length, 40);
    const per = Math.ceil(chunks.length / steps);
    for (let i = 0; i < chunks.length; i += per) {
      await sleep(durationMs / steps, call.signal);
      call.onText(chunks.slice(i, i + per).join(''));
    }
  }

  private gen(prompt: string, text: string): Gen {
    return { text, tokensIn: estimateTokens(prompt), tokensOut: estimateTokens(text) };
  }

  expectedChars(input: ExecuteInput): number {
    return this.deliverable(input).length;
  }

  async propose(call: BrainCall, input: ProposeInput): Promise<Gen> {
    const g = shortGoal(input.goal);
    const angle: Record<string, [string, string, string]> = {
      'High Architect': [
        `The goal — ${g} — splits cleanly into a thin core and a few independent edges.`,
        'A layered design: a small, well-tested core with adapters at the boundaries.',
        'Over-engineering the first iteration; unclear interfaces between parts.',
      ],
      'Grand Strategist': [
        `The fastest credible path to ${g} is to ship a narrow slice first, then widen.`,
        'Milestone-driven: scope → skeleton → core → hardening → release.',
        'Scope creep; parallel work blocking on a shared design decision.',
      ],
      Warden: [
        `Before building ${g}, we must agree on what "done" means and how we will verify it.`,
        'Acceptance criteria up front, a test plan beside the build, a review gate before release.',
        'Untested assumptions, silent failure modes, missing rollback plan.',
      ],
    };
    const [analysis, framework, risks] = angle[input.seatTitle] ?? [
      `We should approach ${g} carefully and incrementally.`,
      'Plan, build, verify, document.',
      'Unknown unknowns.',
    ];
    const text = [
      SIM_BANNER,
      '',
      `## Analysis\n${analysis}`,
      `## Proposed framework\n${framework}`,
      `## Risks\n- ${risks.split('; ').join('\n- ')}`,
      `## Candidate tasks\n- Define scope & success criteria\n- Design the architecture\n- Build the core\n- Write tests\n- Document & ship`,
    ].join('\n\n');
    await this.stream(call, text, this.between(4000, 8000));
    return this.gen(input.goal, text);
  }

  private pickWorker(roster: RosterEntry[], big: boolean, index: number): string {
    const workers = roster.filter((r) => r.controllable);
    if (!workers.length) return '';
    const preferred = workers.filter((w) => (big ? /sonnet|opus|fable/ : /haiku/).test(w.model ?? ''));
    const pool = preferred.length ? preferred : workers;
    return pool[index % pool.length]!.id;
  }

  async synthesize(call: BrainCall, input: SynthesizeInput): Promise<Gen & { plan: Plan }> {
    const g = subject(input.goal);
    type Draft = { key: string; title: string; goal: string; deps: string[]; priority: TaskPriority; big: boolean };
    const drafts: Draft[] = [
      { key: 'scope', title: 'Define scope & success criteria', goal: `Pin down what ${g} must and must not include.`, deps: [], priority: 'high', big: false },
      { key: 'design', title: `Design architecture for ${g}`, goal: 'Produce the component design and interfaces.', deps: ['scope'], priority: 'high', big: true },
      { key: 'build', title: `Build core of ${g}`, goal: 'Implement the core per the design.', deps: ['design'], priority: 'critical', big: true },
      { key: 'tests', title: 'Write tests & verification plan', goal: 'Cover the core with tests and a manual check list.', deps: ['design'], priority: 'normal', big: false },
      { key: 'ship', title: 'Document & ship', goal: 'Write the README, changelog and release checklist.', deps: ['build', 'tests'], priority: 'normal', big: false },
    ];
    if (this.rand() < 0.5) {
      drafts.splice(1, 0, { key: 'research', title: 'Survey prior art & constraints', goal: `Collect constraints and existing approaches relevant to ${g}.`, deps: [], priority: 'low', big: false });
    }
    const tasks: PlanTask[] = drafts.map((d, i) => ({
      key: d.key,
      title: d.title,
      goal: d.goal,
      instructions: `${SIM_BANNER}\n\nYou are working on: ${input.goal}\n\n${d.goal} Keep the deliverable focused and concrete; list open questions at the end.`,
      acceptance: ['Deliverable addresses the task goal directly', 'Open questions are listed explicitly', 'Clearly marked as simulated output'],
      dependsOn: d.deps,
      priority: d.priority,
      suggestedAssignee: this.pickWorker(input.roster, d.big, i),
    }));
    const plan: Plan = {
      summary: `${SIM_BANNER} The council will pursue "${truncate(input.goal, 120)}" in ${tasks.length} steps: agree on scope, design, build the core with tests alongside, then document and ship.`,
      framework: {
        architecture: `A small core for ${g}, wrapped by thin adapters, verified by tests written alongside the build.`,
        principles: ['Smallest useful slice first', 'Every task has explicit acceptance criteria', 'Review before merge'],
        milestones: ['Scope agreed', 'Design approved', 'Core working with tests', 'Documented release'],
      },
      tasks,
    };
    const text = JSON.stringify(plan, null, 2);
    await this.stream(call, `${SIM_BANNER}\n\nSynthesising ${input.proposals.length} proposals into a plan of ${tasks.length} tasks…`, this.between(4000, 6000));
    return { ...this.gen(input.goal, text), plan };
  }

  private deliverable(input: ExecuteInput): string {
    const sections = [
      SIM_BANNER,
      '',
      `Deliverable for **${input.task.title}**${input.reviseNotes ? ' (revised)' : ''}.`,
      `## Approach\n${input.task.goal} This simulated worker outlines how it would proceed for: ${truncate(input.goal, 160)}.`,
      `## Key decisions\n- Keep the first slice small and verifiable\n- Make interfaces explicit\n- Record assumptions next to the work`,
      `## Draft\n\`\`\`text\n(Simulated output: a real worker would write the ${input.task.title.toLowerCase()} here.)\n\`\`\``,
      ...(input.dependencies.length ? [`## Builds on\n${input.dependencies.map((d) => `- ${d.title}`).join('\n')}`] : []),
      ...(input.reviseNotes ? [`## Changes after review\n- ${truncate(input.reviseNotes, 200)}`] : []),
      `## Open questions\n- Which constraints matter most to the user?\n- What is the deadline?`,
    ];
    return sections.join('\n\n');
  }

  async execute(call: BrainCall, input: ExecuteInput): Promise<Gen> {
    const text = this.deliverable(input);
    await this.stream(call, text, this.between(10_000, 25_000));
    return this.gen(input.task.instructions, text);
  }

  async review(call: BrainCall, input: ReviewInput): Promise<Gen & Review> {
    const revise = input.attempt === 1 && this.rand() < 0.2;
    const notes = revise
      ? '(Simulated review) Make the acceptance criteria explicit in the deliverable and tighten the draft.'
      : '(Simulated review) Meets the acceptance criteria.';
    await this.stream(call, notes, this.between(2000, 4000));
    return { ...this.gen(input.output, notes), verdict: revise ? 'revise' : 'approved', notes };
  }

  async verdict(call: BrainCall, input: VerdictInput): Promise<Gen> {
    const done = input.tasks.filter((t) => t.status === 'done').length;
    const text = `${SIM_BANNER}\n\n## Verdict\nThe council considers "${truncate(input.goal, 120)}" complete: ${done}/${input.tasks.length} tasks delivered and reviewed.\n\n**Next step:** add an ANTHROPIC_API_KEY and summon the council again for real deliberation and deliverables.`;
    await this.stream(call, text, this.between(2000, 3000));
    return this.gen(input.summary, text);
  }
}
