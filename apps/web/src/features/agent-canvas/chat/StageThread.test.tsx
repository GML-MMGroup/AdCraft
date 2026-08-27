import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

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

  it("collapses a completed proposal to its selected result until history is requested", () => {
    render(
      <StageThread unit={stageThread()}>
        <div>Full proposal history</div>
      </StageThread>,
    );

    expect(screen.getByText("Silk Pavilion")).toBeTruthy();
    expect(screen.queryByText("Full proposal history")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show World Setting Designer history" }));

    expect(screen.getByText("Full proposal history")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Hide World Setting Designer history" })).toBeTruthy();
  });

  it("summarizes repeated Script Writer activity as revisions", () => {
    render(
      <StageThread
        unit={stageThread({
          key: "stage:script_authoring",
          capability_id: "script_authoring",
          capability_display_name: "Script Writer",
          selected_option: null,
          completed_activity_count: 3,
        })}
      />,
    );

    expect(screen.getByText("Completed 3 revisions")).toBeTruthy();
  });

  it("keeps working and failed threads expanded", () => {
    const { rerender } = render(
      <StageThread unit={stageThread({ status: "working", selected_option: null })}>
        <div>Working detail</div>
      </StageThread>,
    );

    expect(screen.getByText("Working detail")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Hide World Setting Designer history" }).getAttribute("aria-expanded")).toBe("true");

    rerender(
      <StageThread unit={stageThread({ status: "failed", selected_option: null })}>
        <div>Recovery detail</div>
      </StageThread>,
    );

    expect(screen.getByText("Recovery detail")).toBeTruthy();
  });

  it("prioritizes a current failure over a historical selected option", () => {
    const { rerender } = render(<StageThread unit={stageThread({ status: "failed" })} />);

    expect(screen.getByText("This task needs attention.")).toBeTruthy();
    expect(screen.queryByText("Silk Pavilion")).toBeNull();

    rerender(<StageThread unit={stageThread({ status: "working" })} />);
    expect(screen.getByText("Working on this task.")).toBeTruthy();
    expect(screen.queryByText("Silk Pavilion")).toBeNull();
  });

  it("expands a completed thread when an external conversation reveal is requested", () => {
    const { rerender } = render(
      <StageThread unit={stageThread()} revealToken={null}>
        <div>Receipt source</div>
      </StageThread>,
    );
    expect(screen.queryByText("Receipt source")).toBeNull();

    rerender(
      <StageThread unit={stageThread()} revealToken={7}>
        <div>Receipt source</div>
      </StageThread>,
    );

    expect(screen.getByText("Receipt source")).toBeTruthy();
  });
});
