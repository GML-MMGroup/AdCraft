import type { NodeProps } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";
import type { CanvasNode, WorkflowNodeData } from "../types.ts";
import { areWorkflowCanvasNodePropsEqual } from "./WorkflowCanvasNodeModel.ts";

function data(overrides: Partial<WorkflowNodeData> = {}): WorkflowNodeData {
  return {
    title: "Image",
    description: "Reference image",
    status: "pending",
    nodeType: "image-generation",
    kind: "image-generation",
    family: "Image",
    category: "Generation",
    contentPreview: "",
    outputCount: 0,
    previewAssets: [],
    inputPorts: [],
    outputPorts: [],
    ...overrides,
  };
}

function props(nodeData: WorkflowNodeData): NodeProps<CanvasNode> {
  return {
    id: "node-1",
    type: "workflowNode",
    data: nodeData,
    selected: false,
    isConnectable: true,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    dragging: false,
    zIndex: 0,
  };
}

describe("workflow canvas node memoization", () => {
  it("rerenders for preview content and callback changes", () => {
    const current = data({
      onLoadV2SlotVersions: vi.fn(),
    });

    expect(areWorkflowCanvasNodePropsEqual(
      props(current),
      props({ ...current, description: "Updated reference image" }),
    )).toBe(false);
    expect(areWorkflowCanvasNodePropsEqual(
      props(current),
      props({ ...current, outputCount: 2 }),
    )).toBe(false);
    expect(areWorkflowCanvasNodePropsEqual(
      props(current),
      props({ ...current, onLoadV2SlotVersions: vi.fn() }),
    )).toBe(false);
  });
});
