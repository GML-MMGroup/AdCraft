import { describe, expect, it } from "vitest";

import {
  reconcileDragAwareNodes,
  setDraggedNodeIds,
} from "./draggingNodeState.ts";

interface TestNode {
  id: string;
  position: { x: number; y: number };
  selected?: boolean;
  dragging?: boolean;
}

describe("draggingNodeState", () => {
  it("stops preserving dragging state as soon as the pointer is released", () => {
    const activeDraggedNodeIds = new Set<string>();
    const currentNodes: TestNode[] = [{
      id: "image-1",
      position: { x: 280, y: 160 },
      selected: true,
      dragging: true,
    }];
    const canonicalNodes: TestNode[] = [{
      id: "image-1",
      position: { x: 300, y: 180 },
    }];

    setDraggedNodeIds(activeDraggedNodeIds, "image-1", [], true);
    expect(reconcileDragAwareNodes(canonicalNodes, currentNodes, activeDraggedNodeIds)).toEqual([{
      id: "image-1",
      position: { x: 280, y: 160 },
      selected: true,
      dragging: true,
    }]);

    setDraggedNodeIds(activeDraggedNodeIds, "image-1", [], false);
    const afterDragStop = reconcileDragAwareNodes(
      canonicalNodes,
      currentNodes,
      activeDraggedNodeIds,
    );

    expect(afterDragStop).toEqual([{
      id: "image-1",
      position: { x: 300, y: 180 },
      selected: true,
    }]);
    expect(afterDragStop[0]).not.toHaveProperty("dragging");
  });
});
