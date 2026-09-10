import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import {
  AGENT_CANVAS_CONNECTION_RADIUS,
  AGENT_CANVAS_HANDLE_BORDER_INSET,
  AGENT_CANVAS_HANDLE_CENTER_OFFSET,
  AGENT_CANVAS_HANDLE_HIT_SIZE,
  AGENT_CANVAS_HANDLE_RING_SIZE,
  nodeBorderPointFromHandleBoundary,
  nodeBorderPointFromHandleCenter,
} from "./canvasConnectionGeometry.ts";

describe("canvas connection geometry", () => {
  it("keeps the interaction dimensions explicit", () => {
    expect(AGENT_CANVAS_HANDLE_CENTER_OFFSET).toBe(12);
    expect(AGENT_CANVAS_HANDLE_HIT_SIZE).toBe(40);
    expect(AGENT_CANVAS_HANDLE_RING_SIZE).toBe(14);
    expect(AGENT_CANVAS_CONNECTION_RADIUS).toBe(24);
    expect(AGENT_CANVAS_HANDLE_BORDER_INSET).toBe(32);
  });

  it.each([
    [Position.Left, { x: 68, y: 80 }, { x: 100, y: 80 }],
    [Position.Right, { x: 392, y: 80 }, { x: 360, y: 80 }],
    [Position.Top, { x: 180, y: 28 }, { x: 180, y: 60 }],
    [Position.Bottom, { x: 180, y: 252 }, { x: 180, y: 220 }],
  ] as const)("projects a %s Handle boundary back to its node border", (position, handle, border) => {
    expect(nodeBorderPointFromHandleBoundary(handle, position)).toEqual(border);
  });

  it("supports a caller-provided inset without applying viewport zoom", () => {
    expect(nodeBorderPointFromHandleBoundary(
      { x: 725.5, y: 318.25 },
      Position.Right,
      20,
    )).toEqual({ x: 705.5, y: 318.25 });
  });

  it.each([
    [Position.Left, { x: 88, y: 80 }, { x: 100, y: 80 }],
    [Position.Right, { x: 372, y: 80 }, { x: 360, y: 80 }],
    [Position.Top, { x: 180, y: 48 }, { x: 180, y: 60 }],
    [Position.Bottom, { x: 180, y: 232 }, { x: 180, y: 220 }],
  ] as const)("projects a %s preview center back to its node border", (position, handle, border) => {
    expect(nodeBorderPointFromHandleCenter(handle, position)).toEqual(border);
  });
});
