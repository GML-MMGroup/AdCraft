import type { AgentRunPolicy } from "./generated/agent-runtime.js";

export type RunBudgetCode =
  | "agent_run_budget_exceeded"
  | "agent_deadline_exceeded";

export class RunBudgetFailure extends Error {
  constructor(readonly code: RunBudgetCode) {
    super(code);
  }
}

export class RunBudget {
  #turns = 0;
  #toolCalls = 0;
  #handoffs = 0;
  #outputBytes = 0;
  #eventBytes = 0;

  constructor(
    private readonly policy: Required<AgentRunPolicy>,
    private readonly deadlineEpochMs: number,
    private readonly now: () => number = Date.now,
  ) {}

  consumeTurn(): void {
    this.#assertDeadline();
    if (++this.#turns > this.policy.max_turns) this.#overflow();
  }

  consumeToolCall(): void {
    this.#assertDeadline();
    if (++this.#toolCalls > this.policy.max_tool_calls) this.#overflow();
  }

  consumeHandoff(): void {
    this.#assertDeadline();
    if (++this.#handoffs > this.policy.max_handoffs) this.#overflow();
  }

  observeInput(bytes: number): void {
    this.#assertDeadline();
    if (bytes > this.policy.max_input_bytes) this.#overflow();
  }

  observeOutput(bytes: number): void {
    this.#assertDeadline();
    this.#outputBytes += bytes;
    if (this.#outputBytes > this.policy.max_output_bytes) this.#overflow();
  }

  observeEvent(bytes: number, enforceDeadline = true): void {
    if (enforceDeadline) this.#assertDeadline();
    this.#eventBytes += bytes;
    if (this.#eventBytes > this.policy.max_event_bytes) this.#overflow();
  }

  remainingMs(now = this.now()): number {
    return Math.max(0, this.deadlineEpochMs - now);
  }

  #assertDeadline(): void {
    if (this.remainingMs() <= 0) throw new RunBudgetFailure("agent_deadline_exceeded");
  }

  #overflow(): never {
    throw new RunBudgetFailure("agent_run_budget_exceeded");
  }
}
