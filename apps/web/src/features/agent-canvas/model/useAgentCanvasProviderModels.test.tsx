import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  listProviderModels: vi.fn(),
  getModelDefaults: vi.fn(),
}));

vi.mock("../../../api/client.ts", () => ({ api }));

import { useAgentCanvasProviderModels } from "./useAgentCanvasProviderModels.ts";

function node(nodeId: string, nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: nodeType === "script" ? "script" : nodeType === "image" ? "general_image" : "general_text",
    role_contract_version: "ad-media-role-v1",
    title: nodeType,
    status: "draft",
    summary_prompt: null,
    generation_prompt: "Prompt",
    structured_content: {},
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
  };
}

function workflowWith(nodeValue: CanvasNodeV2): AgentCanvasWorkflowV2 {
  return {
    workflow_id: "workflow-1",
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [nodeValue],
    bindings: [],
    assets: [],
  };
}

describe("useAgentCanvasProviderModels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getModelDefaults.mockResolvedValue({
      defaults: { text: "vendor:text-default", video: "vendor:video-default" },
      modes: { text: "explicit", video: "explicit" },
      revisions: { text: 1, video: 1 },
    });
  });

  it.each(["text", "script", "image", "video", "audio"] as const)(
    "loads the canonical catalog filtered for a %s node",
    async (nodeType) => {
      api.listProviderModels.mockResolvedValue({ items: [] });
      const selected = node(`${nodeType}-1`, nodeType);

      renderHook(() => useAgentCanvasProviderModels(workflowWith(selected), selected));

      await waitFor(() => expect(api.listProviderModels).toHaveBeenCalledWith({
        node_type: nodeType,
        include_unavailable: true,
      }));
    },
  );

  it("does not query a model catalog for an Editing node", async () => {
    const editing = node("editing-1", "editing");
    renderHook(() => useAgentCanvasProviderModels(workflowWith(editing), editing));

    await waitFor(() => expect(api.listProviderModels).not.toHaveBeenCalled());
  });

  it("keeps canonical catalog errors available to the inspector", async () => {
    api.listProviderModels.mockRejectedValue(new Error("Model catalog is unavailable."));
    const image = node("image-1", "image");

    const { result } = renderHook(() => useAgentCanvasProviderModels(workflowWith(image), image));

    await waitFor(() => expect(result.current.error).toBe("Model catalog is unavailable."));
  });

  it("keeps the model catalog available when only installation defaults fail", async () => {
    const catalogModel = { model_ref: "vendor:image-model" };
    api.listProviderModels.mockResolvedValue({ items: [catalogModel] });
    api.getModelDefaults.mockRejectedValue(new Error("Defaults are unavailable."));
    const image = node("image-1", "image");

    const { result } = renderHook(() => useAgentCanvasProviderModels(workflowWith(image), image));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.models).toEqual([catalogModel]);
    expect(result.current.defaultModelRef).toBeNull();
    expect(result.current.error).toBe("Default model could not be loaded.");
  });

  it.each([
    ["script", "vendor:text-default"],
    ["video", "vendor:video-default"],
  ] as const)("returns the installation default for a %s node", async (nodeType, expected) => {
    api.listProviderModels.mockResolvedValue({ items: [] });
    const selected = node(`${nodeType}-default`, nodeType);

    const { result } = renderHook(() => useAgentCanvasProviderModels(
      workflowWith(selected),
      selected,
    ));

    await waitFor(() => expect(result.current.defaultModelRef).toBe(expected));
  });
});
