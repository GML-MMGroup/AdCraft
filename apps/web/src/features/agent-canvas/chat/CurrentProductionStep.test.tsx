import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProductionFocusProjection } from "./productionFocusProjection.ts";
import { CurrentProductionStep } from "./CurrentProductionStep.tsx";

afterEach(cleanup);

describe("CurrentProductionStep", () => {
  it("renders a compact actionable runtime status", () => {
    const onViewNodes = vi.fn();
    const focus: ProductionFocusProjection = {
      kind: "waiting",
      title: "Video 01 is waiting",
      detail: "Waiting for Storyboard 01",
      actionLabel: "View blocker",
      nodeIds: ["storyboard-1"],
    };

    render(<CurrentProductionStep focus={focus} onViewNodes={onViewNodes} />);

    expect(screen.getByText("Video 01 is waiting")).toBeTruthy();
    expect(screen.getByText("Waiting for Storyboard 01")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "View blocker" }));
    expect(onViewNodes).toHaveBeenCalledWith(["storyboard-1"]);
  });

  it("uses status semantics without rendering a banner when there is no focus", () => {
    const { container } = render(<CurrentProductionStep focus={null} onViewNodes={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });
});
