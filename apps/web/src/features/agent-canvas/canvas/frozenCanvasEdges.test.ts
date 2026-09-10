import { describe, expect, it } from "vitest";

import {
  captureFrozenCanvasEdges,
  edgeIdsConnectedToNodes,
  partitionCanvasEdges,
} from "./frozenCanvasEdges.ts";

const edges = [
  { id: "a", source: "one", target: "two" },
  { id: "b", source: "two", target: "three" },
  { id: "c", source: "four", target: "five" },
];

describe("frozen canvas edges", () => {
  it("marks every edge touching a dragged node as live", () => {
    expect(edgeIdsConnectedToNodes(edges, new Set(["two"]))).toEqual(new Set(["a", "b"]));
  });

  it("supports multi-node drags and preserves source ordering", () => {
    const result = partitionCanvasEdges(edges, new Set(["one", "five"]));

    expect(result.liveEdges.map((edge) => edge.id)).toEqual(["a", "c"]);
    expect(result.frozenEdges.map((edge) => edge.id)).toEqual(["b"]);
    expect(result.liveEdges[0]).toBe(edges[0]);
    expect(result.frozenEdges[0]).toBe(edges[1]);
  });

  it("does not classify any edge as live without a drag set", () => {
    const result = partitionCanvasEdges(edges, new Set());

    expect(result.liveEdges).toEqual([]);
    expect(result.frozenEdges).toEqual(edges);
  });

  it("captures existing SVG edge markup without recalculating its geometry", () => {
    const root = document.createElement("div");
    root.innerHTML = '<svg><g class="react-flow__edge" data-id="c"><path class="react-flow__edge-path" d="M0 0L20 20" /></g></svg>';

    const snapshots = captureFrozenCanvasEdges(new Set(["c"]), root);

    expect(snapshots).toHaveLength(1);
    expect(snapshots[0]?.id).toBe("c");
    expect(snapshots[0]?.markup).toContain('d="M0 0L20 20"');
  });
});
