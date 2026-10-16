import { Position, type InternalNode } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";
import { findNearbyConnectionHandle } from "./connectionProximity";

function node(id: string, x = 200, overrides: Partial<InternalNode> = {}): InternalNode {
  return {
    id, position: { x, y: 0 }, data: {}, measured: { width: 100, height: 100 },
    internals: {
      positionAbsolute: { x, y: 0 }, z: 0, userNode: { id, position: { x, y: 0 }, data: {} },
      handleBounds: {
        target: [{ id: "input", nodeId: id, type: "target", x: -20, y: 30, width: 40, height: 40, position: Position.Left }],
        source: [{ id: "output", nodeId: id, type: "source", x: 80, y: 30, width: 40, height: 40, position: Position.Right }],
      },
    },
    ...overrides,
  };
}
const from = { type: "source" as const, id: "output" };

describe("visual connection proximity", () => {
  it.each([0.5, 1, 1.5])("uses screen distance at zoom %s and grows stronger near the inlet", zoom => {
    const far = findNearbyConnectionHandle([node("target")], { x: 200 - 91 / zoom, y: 50 }, "source", from, zoom, () => true);
    const near = findNearbyConnectionHandle([node("target")], { x: 200 - 70 / zoom, y: 50 }, "source", from, zoom, () => true);
    const closer = findNearbyConnectionHandle([node("target")], { x: 200 - 40 / zoom, y: 50 }, "source", from, zoom, () => true);
    expect(far).toBeNull();
    expect(near?.center).toEqual({ x: 200, y: 50 });
    expect(closer!.strength).toBeGreaterThan(near!.strength);
  });

  it("uses the nearest permitted opposite handle, excluding hidden, disabled and own nodes", () => {
    const validate = vi.fn(connection => connection.target !== "invalid");
    const result = findNearbyConnectionHandle([
      node("source", 150), node("hidden", 151, { hidden: true }), node("disabled", 152, { connectable: false }),
      node("invalid", 160), node("farther", 220), node("allowed", 200),
    ], { x: 150, y: 50 }, "source", from, 1, validate);
    expect(result?.nodeId).toBe("allowed");
    expect(validate.mock.calls.every(([connection]) => connection.source === "source" && connection.targetHandle === "input")).toBe(true);
  });

  it("validates reversed drags using their actual source and target", () => {
    const validate = vi.fn(() => true);
    const result = findNearbyConnectionHandle([node("source", 0)], { x: 160, y: 50 }, "target", { type: "target", id: "input" }, 1, validate);
    expect(result?.center).toEqual({ x: 100, y: 50 });
    expect(validate).toHaveBeenCalledExactlyOnceWith({ source: "source", sourceHandle: "output", target: "target", targetHandle: "input" });
  });

  it("does not suggest connections before the validation policy is available", () => {
    expect(findNearbyConnectionHandle([node("target")], { x: 160, y: 50 }, "source", from, 1)).toBeNull();
  });
});
