import { describe, expect, it } from "vitest";
import type { WorkflowGraph, WorkflowNode } from "../../../types.ts";
import {
  applyWorkflowDocumentCommand,
  applyWorkflowNodeListCommand,
  projectWorkflowPositionCommand,
} from "./workflowDocumentCommands.ts";
import type { CanvasNode } from "../types.ts";

function node(id: string, status = "pending"): WorkflowNode {
  return {
    id,
    title: id,
    node_type: "image-generation",
    status,
    position: { x: 0, y: 0 },
  };
}

function workflow(nodes: WorkflowNode[]): WorkflowGraph {
  return {
    workflow_id: "workflow-1",
    nodes,
    edges: [],
  };
}

function flowNode(source: WorkflowNode): CanvasNode {
  return {
    id: source.id,
    type: "workflowNode",
    position: source.position ?? { x: 0, y: 0 },
    data: {
      title: source.title,
      description: "",
      status: source.status,
      nodeType: source.node_type,
      kind: source.node_type,
      family: "Image",
      category: "Generation",
      contentPreview: "",
      outputCount: 0,
      previewAssets: [],
      inputPorts: [],
      outputPorts: [],
    },
  };
}

describe("workflow document commands", () => {
  it("patches only affected nodes and preserves all unaffected references", () => {
    const first = node("first");
    const second = node("second");
    const current = workflow([first, second]);

    const next = applyWorkflowDocumentCommand(current, {
      type: "patch-nodes",
      nodeIds: ["first"],
      patch: { status: "running" },
    });

    expect(next).not.toBe(current);
    expect(next.nodes[0]).not.toBe(first);
    expect(next.nodes[0].status).toBe("running");
    expect(next.nodes[1]).toBe(second);
  });

  it("returns the original document when a command makes no semantic change", () => {
    const first = node("first");
    const current = workflow([first]);

    expect(applyWorkflowDocumentCommand(current, {
      type: "patch-nodes",
      nodeIds: ["first"],
      patch: { status: "pending" },
    })).toBe(current);
  });

  it("moves one node without rebuilding the remaining node collection", () => {
    const first = node("first");
    const second = node("second");
    const next = applyWorkflowNodeListCommand([first, second], {
      type: "move-node",
      nodeId: "second",
      position: { x: 320, y: 180 },
    });

    expect(next[0]).toBe(first);
    expect(next[1]).not.toBe(second);
    expect(next[1].position).toEqual({ x: 320, y: 180 });
  });

  it("applies an auto-layout position map with structural sharing", () => {
    const first = node("first");
    const second = node("second");
    const next = applyWorkflowNodeListCommand([first, second], {
      type: "set-node-positions",
      positions: new Map([
        ["first", { x: 0, y: 0 }],
        ["second", { x: 640, y: 240 }],
      ]),
    });

    expect(next[0]).toBe(first);
    expect(next[1]).not.toBe(second);
    expect(next[1].position).toEqual({ x: 640, y: 240 });
  });

  it("applies runtime transforms through the same document boundary", () => {
    const first = node("first");
    const second = node("second");
    const next = applyWorkflowNodeListCommand([first, second], {
      type: "transform-nodes",
      transformWorkflowNode: (current) => (
        current.id === "second" ? { ...current, status: "completed" } : current
      ),
      transformCanvasNode: (current) => current,
    });

    expect(next[0]).toBe(first);
    expect(next[1]).not.toBe(second);
    expect(next[1].status).toBe("completed");
  });

  it("composes consecutive position commands before React renders new props", () => {
    const first = node("first");
    const second = node("second");
    let projection = {
      canvasNodes: [first, second],
      flowNodes: [flowNode(first), flowNode(second)],
    };

    projection = projectWorkflowPositionCommand(projection, {
      type: "move-node",
      nodeId: "first",
      position: { x: 120, y: 80 },
    });
    projection = projectWorkflowPositionCommand(projection, {
      type: "move-node",
      nodeId: "second",
      position: { x: 420, y: 220 },
    });

    expect(projection.canvasNodes.map((entry) => entry.position)).toEqual([
      { x: 120, y: 80 },
      { x: 420, y: 220 },
    ]);
    expect(projection.flowNodes.map((entry) => entry.position)).toEqual([
      { x: 120, y: 80 },
      { x: 420, y: 220 },
    ]);
  });
});
