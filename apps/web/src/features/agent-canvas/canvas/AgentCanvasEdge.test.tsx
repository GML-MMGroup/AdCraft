import { getBezierPath, Position, type EdgeProps } from "@xyflow/react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentCanvasEdge } from "./AgentCanvasEdge.tsx";

describe("AgentCanvasEdge", () => {
  it("draws between node-border midpoints instead of external Handle boundaries", () => {
    const props: EdgeProps = {
      id: "edge-1",
      source: "source",
      target: "target",
      sourceX: 392,
      sourceY: 100,
      targetX: 468,
      targetY: 160,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      markerEnd: "url(#arrow)",
      interactionWidth: 28,
    };
    const expectedPath = getBezierPath({
      sourceX: 360,
      sourceY: 100,
      targetX: 500,
      targetY: 160,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    })[0];

    const { container } = render(<svg><AgentCanvasEdge {...props} /></svg>);
    const path = container.querySelector<SVGPathElement>(".react-flow__edge-path");

    expect(path?.getAttribute("d")).toBe(expectedPath);
    expect(path?.getAttribute("marker-end")).toBe("url(#arrow)");
    expect(container.querySelector(".react-flow__edge-interaction")?.getAttribute("d")).toBe(expectedPath);
  });
});
