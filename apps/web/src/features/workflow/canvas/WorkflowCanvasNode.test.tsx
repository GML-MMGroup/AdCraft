import { cleanup, render, screen } from "@testing-library/react";
import type { NodeProps } from "@xyflow/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasNode, WorkflowNodeData } from "../types.ts";
import { WorkflowCanvasNode } from "./WorkflowCanvasNode.tsx";

vi.mock("@xyflow/react", () => ({
  Handle: ({ id, className }: { id?: string; className?: string }) => (
    <span data-testid={`handle-${id ?? "unknown"}`} className={className} />
  ),
  Position: {
    Left: "left",
    Right: "right",
  },
  useUpdateNodeInternals: () => vi.fn(),
}));

function nodeData(overrides: Partial<WorkflowNodeData> = {}): WorkflowNodeData {
  return {
    title: "Product image generator",
    description: "Generated product image",
    status: "completed",
    nodeType: "product-generation",
    kind: "product-generation",
    family: "Image",
    category: "Generation",
    contentPreview: "",
    outputCount: 1,
    previewAssets: [
      {
        asset_id: "asset-1",
        asset_type: "image",
        asset_role: "generated",
        filename: "product.png",
        mime_type: "image/png",
        local_path: "/media/product.png",
        preview_path: "/media/product.png",
      },
    ],
    inputPorts: [],
    outputPorts: [],
    ...overrides,
  };
}

function nodeProps(data: WorkflowNodeData): NodeProps<CanvasNode> {
  return {
    id: "node-1",
    type: "workflowNode",
    data,
    selected: false,
    isConnectable: true,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    dragging: false,
    zIndex: 0,
  };
}

afterEach(cleanup);

describe("WorkflowCanvasNode media-first shell", () => {
  it("uses a border-aligned type marker without rendering a title header", () => {
    const { container } = render(<WorkflowCanvasNode {...nodeProps(nodeData())} />);

    const card = container.querySelector(".workflow-card");
    const marker = screen.getByLabelText("Image node type");

    expect(card?.classList.contains("is-media-surface")).toBe(true);
    expect(marker.classList.contains("workflow-node-type-marker")).toBe(true);
    expect(marker.parentElement).toBe(card);
    expect(container.querySelector(".workflow-node-drag-rail")?.parentElement).toBe(card);
    expect(container.querySelector(".workflow-card-identity")).toBeNull();
    expect(container.querySelector(".workflow-card-identity-divider")).toBeNull();
    expect(screen.queryByText("Product image generator")).toBeNull();
    expect(screen.getByText("completed")).toBeTruthy();
  });

  it("keeps a type marker for text and audio nodes without adding a media surface class", () => {
    const { container, rerender } = render(
      <WorkflowCanvasNode
        {...nodeProps(nodeData({
          family: "Text",
          kind: "script",
          previewAssets: [],
          contentPreview: "Script content",
        }))}
      />,
    );

    expect(screen.getByLabelText("Text node type")).toBeTruthy();
    expect(container.querySelector(".workflow-card")?.classList.contains("is-media-surface")).toBe(false);

    rerender(
      <WorkflowCanvasNode
        {...nodeProps(nodeData({
          family: "Audio",
          kind: "bgm",
          previewAssets: [],
          contentPreview: "Ambient soundtrack",
        }))}
      />,
    );

    expect(screen.getByLabelText("Audio node type")).toBeTruthy();
  });
});
