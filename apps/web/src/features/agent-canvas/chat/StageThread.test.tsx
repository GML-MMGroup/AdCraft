import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const visual = vi.hoisted(() => ({ snapshot: vi.fn(), retry: vi.fn() }));

vi.mock("./agent-role-animation/agentRoleVisualResource.ts", async (importOriginal) => ({
  ...await importOriginal<typeof import("./agent-role-animation/agentRoleVisualResource.ts")>(),
  retryRoleVisual: visual.retry,
}));

vi.mock("./agent-role-animation/useAgentRoleVisual.ts", () => ({
  useAgentRoleVisual: visual.snapshot,
}));

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

const readyVisual = {
  status: "ready",
  source: "/role.png",
  Artwork: () => null,
  error: null,
  generation: 1,
  fallbackKind: "none",
} as const;

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
  beforeEach(() => {
    visual.snapshot.mockReturnValue(readyVisual);
  });

  afterEach(() => cleanup());

  it("keeps a working placeholder until artwork is ready, then atomically shows the role identity", () => {
    visual.snapshot.mockReturnValue({ ...readyVisual, status: "pending", Artwork: null });
    const { container, rerender } = render(
      <StageThread motionState="working" unit={stageThread({ status: "working" })}>
        <div>Working detail</div>
      </StageThread>,
    );

    expect(container.querySelector(".agent-chat__stage-thread--loading")).toBeTruthy();
    expect(screen.getByRole("status", { name: "Working" })).toBeTruthy();
    expect(screen.queryByText("World Setting Designer")).toBeNull();
    expect(screen.queryByText("Working detail")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector('[data-testid="agent-role-animation-double"]')).toBeNull();

    visual.snapshot.mockReturnValue(readyVisual);
    rerender(
      <StageThread motionState="working" unit={stageThread({ status: "working" })}>
        <div>Working detail</div>
      </StageThread>,
    );

    expect(screen.getByText("Working detail")).toBeTruthy();
    expect(screen.getByText("World Setting Designer")).toBeTruthy();
    expect(screen.queryByRole("status", { name: "Working" })).toBeNull();
    expect(container.querySelector('[data-testid="agent-role-animation-double"]')).toBeTruthy();
  });

  it("replaces a failed resource with an explicit bounded retry, never role text or a bitmap", () => {
    visual.snapshot.mockReturnValue({ ...readyVisual, status: "fallback", Artwork: null, error: "load failed", retryAvailable: true });
    const { container, rerender } = render(<StageThread motionState="working" unit={stageThread({ status: "working" })} />);
    expect(screen.getByRole("alert")).toBeTruthy();
    screen.getByRole("button", { name: "Retry animation" }).click();
    expect(visual.retry).toHaveBeenCalledWith("world_setting", "animated");
    expect(screen.queryByText("World Setting Designer")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    visual.snapshot.mockReturnValue({ ...readyVisual, status: "fallback", Artwork: null, error: "load failed", retryAvailable: false });
    rerender(<StageThread motionState="working" unit={stageThread({ status: "working" })} />);
    expect(screen.getByRole<HTMLButtonElement>("button").disabled).toBe(true);
  });

  it("does not flash a working role when it terminates before its artwork loads", () => {
    visual.snapshot.mockReturnValue({ ...readyVisual, status: "pending", Artwork: null });
    const { rerender } = render(<StageThread motionState="working" unit={stageThread({ status: "working" })} />);
    visual.snapshot.mockReturnValue({ ...readyVisual, Artwork: null });
    rerender(<StageThread motionState="idle" unit={stageThread({ status: "failed" })}><div>Failure details</div></StageThread>);
    expect(screen.getByText("Failure details")).toBeTruthy();
    expect(screen.getByTestId("agent-role-animation-double").dataset.motionState).toBe("idle");
    visual.snapshot.mockReturnValue(readyVisual);
    rerender(<StageThread motionState="idle" unit={stageThread({ status: "failed" })} />);
    expect(screen.getByTestId("agent-role-animation-double").dataset.motionState).toBe("idle");
  });

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

  it("forwards the working state to the stage identity animation", () => {
    render(
      <StageThread
        motionState="working"
        unit={stageThread({ status: "working", selected_option: null })}
      />,
    );

    const animation = document.querySelector<HTMLElement>(
      '[data-testid="agent-role-animation-double"]',
    );
    expect(animation?.dataset.capabilityId).toBe("world_setting");
    expect(animation?.dataset.motionState).toBe("working");
  });
});
