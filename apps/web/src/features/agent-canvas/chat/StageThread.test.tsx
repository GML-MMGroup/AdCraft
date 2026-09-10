import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./agent-role-animation/AgentRoleAnimation.tsx", () => ({
  AgentRoleAnimation: ({
    capabilityId,
    motionState,
  }: {
    capabilityId: string;
    motionState: string;
  }) => (
    <span
      data-testid="agent-role-animation-double"
      data-capability-id={capabilityId}
      data-motion-state={motionState}
    />
  ),
}));

import type { StageThreadUnit } from "./stageThreadProjection.ts";
import { StageThread } from "./StageThread.tsx";

function stageThread(overrides: Partial<StageThreadUnit> = {}): StageThreadUnit {
  return {
    unit_type: "stage_thread",
    key: "stage:world_setting",
    capability_id: "world_setting",
    capability_display_name: "World Setting Designer",
    sequence: 1,
    status: "completed",
    planning: [],
    activities: [],
    proposals: [],
    receipts: [],
    selected_option: {
      option_id: "option-1",
      title: "Silk Pavilion",
      public_summary: "A flowing silk interior built around the product ritual.",
      key_decisions: [],
    },
    completed_activity_count: 1,
    ...overrides,
  };
}

describe("StageThread", () => {
  afterEach(() => cleanup());

  it("always shows workflow history and places the canvas action in the header", () => {
    render(
      <StageThread motionState="idle" unit={stageThread()} result={<button type="button">View on canvas</button>}>
        <div>Full proposal history</div>
      </StageThread>,
    );

    expect(screen.getByText("Full proposal history")).toBeTruthy();
    expect(screen.getByRole("button", { name: "View on canvas" })).toBeTruthy();
    expect(document.querySelector('[data-testid="agent-capability-icon"]')).toBeTruthy();
    expect(screen.queryByText("Silk Pavilion")).toBeNull();
    expect(screen.queryByRole("button", { name: /history/i })).toBeNull();
  });

  it("keeps working and failed threads expanded", () => {
    const { rerender } = render(
      <StageThread motionState="working" unit={stageThread({ status: "working", selected_option: null })}>
        <div>Working detail</div>
      </StageThread>,
    );

    expect(screen.getByText("Working detail")).toBeTruthy();
    rerender(
      <StageThread motionState="idle" unit={stageThread({ status: "failed", selected_option: null })}>
        <div>Recovery detail</div>
      </StageThread>,
    );

    expect(screen.getByText("Recovery detail")).toBeTruthy();
  });

  it("does not repeat the thread status in the capability header", () => {
    const { rerender } = render(
      <StageThread motionState="idle" unit={stageThread({ status: "failed" })} />,
    );

    expect(screen.queryByText("Needs attention")).toBeNull();
    expect(screen.queryByText("Silk Pavilion")).toBeNull();

    rerender(<StageThread motionState="working" unit={stageThread({ status: "working" })} />);
    expect(screen.queryByText("Working")).toBeNull();
    expect(screen.queryByText("Silk Pavilion")).toBeNull();
  });

  it("always renders completed thread details", () => {
    render(
      <StageThread motionState="idle" unit={stageThread()}>
        <div>Receipt source</div>
      </StageThread>,
    );
    expect(screen.getByText("Receipt source")).toBeTruthy();
  });

  it("forwards waiting state to the stage identity animation", () => {
    render(
      <StageThread
        motionState="waiting"
        unit={stageThread({ status: "working", selected_option: null })}
      />,
    );

    const animation = document.querySelector<HTMLElement>(
      '[data-testid="agent-role-animation-double"]',
    );
    expect(animation?.dataset.capabilityId).toBe("world_setting");
    expect(animation?.dataset.motionState).toBe("waiting");
  });
});
