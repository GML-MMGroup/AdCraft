import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { AgentCanvasInlineWorkbench } from "./AgentCanvasInlineWorkbench.tsx";

function makeNode(type: CanvasNodeTypeV2, status: CanvasNodeV2["status"] = "draft"): CanvasNodeV2 {
  return {
    node_id: `${type}-node`,
    workflow_id: "workflow-1",
    node_type: type,
    creative_role: type === "text" ? "general_text" : type === "script" ? "script" : type === "image" ? "general_image" : type === "video" ? "general_video" : type === "audio" ? "general_audio" : "editing",
    role_contract_version: "ad-media-role-v1",
    title: `${type} node`,
    status,
    summary_prompt: null,
    generation_prompt: type === "image" ? "A quiet fragrance film" : null,
    structured_content: type === "text" ? { content: "Initial brief" } : type === "script" ? { script_text: "Open on dawn." } : {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 120, y: 140 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-31T00:00:00Z",
    updated_at: "2026-07-31T00:00:00Z",
  };
}

function makeWorkflow(node: CanvasNodeV2): AgentCanvasWorkflowV2 {
  return {
    workflow_id: "workflow-1",
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [node],
    bindings: [],
    assets: [],
  };
}

function renderWorkbench(node: CanvasNodeV2, overrides: Record<string, unknown> = {}) {
  const props = {
    workflow: makeWorkflow(node),
    node,
    patchNode: vi.fn().mockResolvedValue(undefined),
    onRun: vi.fn().mockResolvedValue(undefined),
    onSaveVariation: vi.fn().mockResolvedValue(undefined),
    onDiscardVariation: vi.fn().mockResolvedValue(undefined),
    onMaterializeVariation: vi.fn().mockResolvedValue(null),
    onSaveImageToLibrary: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onOpenEditing: vi.fn(),
    onOpenAssets: vi.fn(),
    onUploadReferences: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<AgentCanvasInlineWorkbench {...props} />);
  return props;
}

afterEach(() => cleanup());

describe("AgentCanvasInlineWorkbench", () => {
  it.each<[CanvasNodeTypeV2, string]>([
    ["text", "Text content"],
    ["script", "Script content"],
    ["image", "Generation prompt"],
  ])("uses a compact prompt composer for %s without node name chrome", (nodeType, textareaLabel) => {
    const node = makeNode(nodeType);
    renderWorkbench(node);

    expect(screen.getByLabelText(textareaLabel)).toBeTruthy();
    expect(screen.queryByText("Name")).toBeNull();
    expect(screen.queryByText(node.title)).toBeNull();
    expect(screen.queryByText(nodeType.toUpperCase())).toBeNull();
  });

  it("saves structured text directly from the node workbench without offering a run action", async () => {
    const node = makeNode("text");
    const props = renderWorkbench(node);

    fireEvent.change(screen.getByLabelText("Text content"), {
      target: { value: "A revised campaign brief" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save text node" }));

    await waitFor(() => {
      expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
        structured_content: { content: "A revised campaign brief" },
      }));
    });
    expect(screen.queryByRole("button", { name: /run text node/i })).toBeNull();
  });

  it("saves a ready media prompt before creating a sibling variation", async () => {
    const node = makeNode("image", "ready");
    const props = renderWorkbench(node);

    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "A cinematic amber fragrance film" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate image variation" }));

    await waitFor(() => {
      expect(props.onSaveVariation).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
        generation_prompt: "A cinematic amber fragrance film",
      }));
    });
    expect(props.onMaterializeVariation).toHaveBeenCalledWith(node, "generate");
  });

  it("opens the shared assets browser from the media workbench", () => {
    const props = renderWorkbench(makeNode("video"));

    fireEvent.click(screen.getByRole("button", { name: "Choose asset references" }));

    expect(props.onOpenAssets).toHaveBeenCalledOnce();
  });

  it("opens the local upload control from the media workbench", () => {
    const props = renderWorkbench(makeNode("image"));

    fireEvent.click(screen.getByRole("button", { name: "Upload image reference" }));

    expect(props.onUploadReferences).toHaveBeenCalledOnce();
  });
});
