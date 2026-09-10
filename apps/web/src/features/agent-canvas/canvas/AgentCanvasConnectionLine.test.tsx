import { getBezierPath, Position, type ConnectionLineComponentProps } from "@xyflow/react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentCanvasConnectionLine } from "./AgentCanvasConnectionLine.tsx";
import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";

function connectionProps(
  overrides: Partial<ConnectionLineComponentProps<AgentCanvasFlowNode>> = {},
): ConnectionLineComponentProps<AgentCanvasFlowNode> {
  return {
    connectionLineType: "bezier",
    fromNode: {} as ConnectionLineComponentProps<AgentCanvasFlowNode>["fromNode"],
    fromHandle: {} as ConnectionLineComponentProps<AgentCanvasFlowNode>["fromHandle"],
    fromX: 372,
    fromY: 100,
    toX: 600,
    toY: 190,
    fromPosition: Position.Right,
    toPosition: Position.Left,
    connectionStatus: null,
    toNode: null,
    toHandle: null,
    pointer: { x: 600, y: 190 },
    ...overrides,
  };
}

describe("AgentCanvasConnectionLine", () => {
  it("starts at the source border and follows the pointer while freely dragging", () => {
    const props = connectionProps();
    const expectedPath = getBezierPath({
      sourceX: 360,
      sourceY: 100,
      targetX: 600,
      targetY: 190,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    })[0];

    const { container } = render(<svg><AgentCanvasConnectionLine {...props} /></svg>);

    expect(container.querySelector(".agent-canvas-connection-line")?.getAttribute("d")).toBe(expectedPath);
  });

  it("ends at the target border when React Flow supplies a snapped Handle", () => {
    const props = connectionProps({
      toX: 488,
      toY: 160,
      connectionStatus: "valid",
      toNode: {} as ConnectionLineComponentProps<AgentCanvasFlowNode>["toNode"],
      toHandle: {} as ConnectionLineComponentProps<AgentCanvasFlowNode>["toHandle"],
    });
    const expectedPath = getBezierPath({
      sourceX: 360,
      sourceY: 100,
      targetX: 500,
      targetY: 160,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    })[0];

    const { container } = render(<svg><AgentCanvasConnectionLine {...props} /></svg>);
    const path = container.querySelector(".agent-canvas-connection-line");

    expect(path?.getAttribute("d")).toBe(expectedPath);
    expect(path?.getAttribute("data-connection-status")).toBe("valid");
  });

  it("keeps an invalid target at the pointer even when a nearby handle is supplied", () => {
    const props = connectionProps({
      connectionStatus: "invalid",
      toNode: {} as ConnectionLineComponentProps<AgentCanvasFlowNode>["toNode"],
      toHandle: {} as ConnectionLineComponentProps<AgentCanvasFlowNode>["toHandle"],
    });
    const expectedPath = getBezierPath({
      sourceX: 360, sourceY: 100, targetX: 600, targetY: 190,
      sourcePosition: Position.Right, targetPosition: Position.Left,
    })[0];
    const { container } = render(<svg><AgentCanvasConnectionLine {...props} /></svg>);
    expect(container.querySelector("path")?.getAttribute("d")).toBe(expectedPath);
  });

  it("anchors reverse drags from an input center to an output center", () => {
    const props = connectionProps({
      fromX: 488, fromY: 160, fromPosition: Position.Left,
      toX: 372, toY: 100, toPosition: Position.Right,
      connectionStatus: "valid",
      toNode: {} as ConnectionLineComponentProps<AgentCanvasFlowNode>["toNode"],
      toHandle: {} as ConnectionLineComponentProps<AgentCanvasFlowNode>["toHandle"],
    });
    const expectedPath = getBezierPath({
      sourceX: 500, sourceY: 160, targetX: 360, targetY: 100,
      sourcePosition: Position.Left, targetPosition: Position.Right,
    })[0];
    const { container } = render(<svg><AgentCanvasConnectionLine {...props} /></svg>);
    expect(container.querySelector("path")?.getAttribute("d")).toBe(expectedPath);
  });
});
