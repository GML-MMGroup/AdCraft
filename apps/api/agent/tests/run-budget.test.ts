import { describe, expect, it, vi } from "vitest";

import { RunBudget } from "../src/run-budget.js";

const policy = {
  max_turns: 1,
  max_tool_calls: 1,
  max_handoffs: 1,
  timeout_seconds: 2,
  max_input_bytes: 10,
  max_output_bytes: 10,
  max_event_bytes: 10,
};

describe("RunBudget", () => {
  it("permits each exact limit and blocks the next operation", () => {
    const budget = new RunBudget(policy, 2_000, () => 1_000);
    budget.consumeTurn();
    budget.consumeToolCall();
    budget.consumeHandoff();
    budget.observeInput(10);
    budget.observeOutput(10);
    budget.observeEvent(10);

    expect(() => budget.consumeTurn()).toThrow("agent_run_budget_exceeded");
  });

  it("checks the shared absolute deadline before activity", () => {
    const now = vi.fn(() => 2_000);
    const budget = new RunBudget(policy, 2_000, now);

    expect(budget.remainingMs()).toBe(0);
    expect(() => budget.consumeToolCall()).toThrow("agent_deadline_exceeded");
  });

  it.each([
    ["input", (budget: RunBudget) => budget.observeInput(11)],
    ["output", (budget: RunBudget) => budget.observeOutput(11)],
    ["event", (budget: RunBudget) => budget.observeEvent(11)],
  ])("enforces the %s byte limit", (_name, exercise) => {
    expect(() => exercise(new RunBudget(policy, 2_000, () => 1_000))).toThrow(
      "agent_run_budget_exceeded",
    );
  });
});
