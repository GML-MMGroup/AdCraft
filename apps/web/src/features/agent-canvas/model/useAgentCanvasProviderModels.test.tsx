import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasProviderCapabilities: vi.fn(),
}));

vi.mock("../../../api/v2Client.ts", () => ({
  isV2ApiError: (value: unknown) => Boolean(
    value && typeof value === "object" && "code" in value,
  ),
  v2Api: api,
}));

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
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
  };
}

describe("useAgentCanvasProviderModels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not request media Provider capabilities for Script nodes", async () => {
    api.agentCanvasProviderCapabilities.mockResolvedValue([]);
    const script = node("script-1", "script");
    const workflow = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 1,
      layout_revision: 1,
      nodes: [script],
      bindings: [{
        binding_id: "audio-input",
        workflow_id: "workflow-1",
        source: { kind: "node_output", source_node_id: "audio-1" },
        target_node_id: script.node_id,
        input_role: "audio_reference",
        required: false,
        enabled: true,
        order: 0,
        label: null,
        metadata: {},
        created_at: "2026-07-30T00:00:00Z",
        updated_at: "2026-07-30T00:00:00Z",
      }],
      assets: [],
    } as unknown as AgentCanvasWorkflowV2;

    renderHook(() => useAgentCanvasProviderModels(workflow, script));

    await waitFor(() => expect(api.agentCanvasProviderCapabilities).not.toHaveBeenCalled());
  });

  it("keeps the backend provider_input_unsupported message available to the inspector", async () => {
    api.agentCanvasProviderCapabilities.mockRejectedValue(
      Object.assign(new Error("Selected model does not accept audio input."), {
        code: "provider_input_unsupported",
      }),
    );
    const image = node("image-1", "image");
    const workflow = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 1,
      layout_revision: 1,
      nodes: [image],
      bindings: [],
      assets: [],
    } as AgentCanvasWorkflowV2;

    const { result } = renderHook(() => useAgentCanvasProviderModels(workflow, image));

    await waitFor(() => expect(result.current.error).toBe(
      "Provider input unsupported: Selected model does not accept audio input.",
    ));
  });
});
