import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { ConversationCanvasLocation } from "./conversationCanvasLinks.ts";
import { ConversationNodeLinks } from "./ConversationNodeLinks.tsx";

afterEach(cleanup);

const nodes = [
  { node_id: "node-1", title: "Storyboard 01" },
  { node_id: "node-2", title: "Video 01" },
] as CanvasNodeV2[];

function location(overrides: Partial<ConversationCanvasLocation> = {}): ConversationCanvasLocation {
  return {
    key: "stage:storyboard_design",
    kind: "stage_thread",
    sequence: 1,
    createdNodeIds: ["node-1"],
    updatedNodeIds: ["node-2"],
    deletedNodeIds: [],
    relatedNodeIds: [],
    navigableNodeIds: ["node-1", "node-2"],
    ...overrides,
  };
}

describe("ConversationNodeLinks", () => {
  it("hides node-count summaries and keeps the canvas locator", () => {
    const onViewNodes = vi.fn();
    render(
      <ConversationNodeLinks
        location={location({ navigableNodeIds: ["node-1", "missing-node"] })}
        nodes={nodes}
        variant="result"
        onViewNodes={onViewNodes}
      />,
    );

    expect(screen.queryByText(/created|updated|deleted/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "View result nodes on canvas" }));
    expect(onViewNodes).toHaveBeenCalledWith(["node-1"]);
    expect(document.body.textContent).not.toContain("missing-node");
  });

  it("renders linked messages as a compact list of user-facing node names", () => {
    render(
      <ConversationNodeLinks
        location={location({
          createdNodeIds: [],
          updatedNodeIds: [],
          relatedNodeIds: ["node-1", "node-2"],
          navigableNodeIds: ["node-1", "node-2"],
        })}
        nodes={nodes}
        variant="related"
        onViewNodes={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "View related nodes on canvas" }).textContent)
      .toBe("Related · Storyboard 01 · Video 01");
  });

  it("does not render deleted-only changes without a navigable node", () => {
    render(
      <ConversationNodeLinks
        location={location({
          createdNodeIds: [],
          updatedNodeIds: [],
          deletedNodeIds: ["deleted-node"],
          navigableNodeIds: [],
        })}
        nodes={nodes}
        variant="receipt"
        onViewNodes={vi.fn()}
      />,
    );

    expect(screen.queryByText(/node|deleted/)).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
