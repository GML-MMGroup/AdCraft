import { describe, expect, it } from "vitest";

import {
  deferNodeSnapshotDuringDrag,
  finishNodeDrag,
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

  it("defers a complete runtime snapshot while any node is being dragged", () => {
    const activeDraggedNodeIds = new Set(["image-1"]);
    const currentNodes: TestNode[] = [{
      id: "image-1",
      position: { x: 280, y: 160 },
      dragging: true,
    }];
    const runtimeSnapshot: TestNode[] = [{
      id: "image-1",
      position: { x: 120, y: 80 },
    }, {
      id: "video-1",
      position: { x: 620, y: 80 },
    }];

    expect(deferNodeSnapshotDuringDrag(
      runtimeSnapshot,
      currentNodes,
      activeDraggedNodeIds,
    )).toEqual({
      nodes: null,
      pendingNodes: runtimeSnapshot,
    });
  });

  it("rebuilds the complete latest snapshot after a partial multi-drag stop callback", () => {
    const activeDraggedNodeIds = new Set(["image-1", "video-1"]);
    const currentNodes: TestNode[] = [{
      id: "image-1",
      position: { x: 280, y: 160 },
      selected: true,
      dragging: true,
    }, {
      id: "video-1",
      position: { x: 680, y: 160 },
      selected: true,
      dragging: true,
    }];
    const latestSnapshot: TestNode[] = [{
      id: "image-1",
      position: { x: 120, y: 80 },
    }, {
      id: "video-1",
      position: { x: 520, y: 80 },
    }, {
      id: "audio-1",
      position: { x: 920, y: 80 },
    }];

    const result = finishNodeDrag(
      latestSnapshot,
      currentNodes,
      activeDraggedNodeIds,
      [{ id: "image-1", position: { x: 300, y: 180 }, dragging: false }],
    );

    expect(activeDraggedNodeIds).toEqual(new Set());
    expect(result.positions).toEqual([
      { node_id: "image-1", x: 300, y: 180 },
      { node_id: "video-1", x: 680, y: 160 },
    ]);
    expect(result.nodes).toEqual([{
      id: "image-1",
      position: { x: 300, y: 180 },
      selected: true,
    }, {
      id: "video-1",
      position: { x: 680, y: 160 },
      selected: true,
    }, {
      id: "audio-1",
      position: { x: 920, y: 80 },
      selected: false,
    }]);
  });

  it("rejects non-finite drag-stop coordinates from rendering and persistence", () => {
    const activeDraggedNodeIds = new Set(["image-1", "video-1"]);
    const currentNodes: TestNode[] = [{
      id: "image-1",
      position: { x: 280, y: 160 },
      dragging: true,
    }, {
      id: "video-1",
      position: { x: 680, y: 160 },
      dragging: true,
    }];
    const latestSnapshot: TestNode[] = [{
      id: "image-1",
      position: { x: 120, y: 80 },
    }, {
      id: "video-1",
      position: { x: 520, y: 80 },
    }];

    const result = finishNodeDrag(
      latestSnapshot,
      currentNodes,
      activeDraggedNodeIds,
      [
        { id: "image-1", position: { x: Number.NaN, y: 180 } },
        { id: "video-1", position: { x: 700, y: Number.POSITIVE_INFINITY } },
      ],
    );

    expect(result.positions).toEqual([]);
    expect(result.nodes.map(({ position }) => position)).toEqual([
      { x: 120, y: 80 },
      { x: 520, y: 80 },
    ]);
  });

  it("keeps non-finite snapshot coordinates out of React Flow", () => {
    const currentNodes: TestNode[] = [{
      id: "image-1",
      position: { x: 280, y: 160 },
    }];
    const malformedSnapshot: TestNode[] = [{
      id: "image-1",
      position: { x: Number.NaN, y: 80 },
    }, {
      id: "video-1",
      position: { x: 520, y: Number.NEGATIVE_INFINITY },
    }];

    expect(reconcileDragAwareNodes(
      malformedSnapshot,
      currentNodes,
      new Set(),
    ).map(({ position }) => position)).toEqual([
      { x: 280, y: 160 },
      { x: 0, y: 0 },
    ]);
  });
});
