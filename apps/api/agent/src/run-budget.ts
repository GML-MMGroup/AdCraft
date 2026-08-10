import type { AgentRunPolicy } from "./generated/agent-runtime.js";

export type RunBudgetCode =
  | "agent_run_budget_exceeded"
  | "agent_deadline_exceeded";

const OPERATION_DEADLINES_SECONDS: Readonly<Record<string, number>> = {
  decide_turn_intent: 180,
  decide_next_action: 180,
  command_replan: 180,
  compile_video_parameters: 180,
  propose_world_setting_options: 300,
  propose_product_options: 300,
  propose_prop_options: 300,
  propose_character_options: 300,
  propose_scene_options: 300,
  propose_script_options: 300,
  propose_storyboard_options: 300,
  propose_video_options: 300,
  propose_bgm_options: 300,
  materialize_quick_media: 420,
  execute_canvas_text: 420,
  execute_canvas_script: 600,
};

export function operationDeadlineSeconds(operation: string): number {
  return OPERATION_DEADLINES_SECONDS[operation] ?? 300;
}

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
    private readonly policy: Required<
      Pick<
        AgentRunPolicy,
        | "max_turns"
        | "max_tool_calls"
        | "max_handoffs"
        | "timeout_seconds"
        | "max_input_bytes"
        | "max_output_bytes"
        | "max_event_bytes"
      >
    >,
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
