import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import type { ReadyMediaVariationDraft } from "./readyMediaVariation.ts";

const { createAgentCanvasNode, setAgentCanvasWorkflow } = vi.hoisted(() => ({
  createAgentCanvasNode: vi.fn(),
  setAgentCanvasWorkflow: vi.fn(),
}));

vi.mock("../../../api/v2Client.ts", () => ({
  v2Api: {
    createAgentCanvasNode,
  },
}));

const source: CanvasNodeV2 = {
  node_id: "image-source",
  workflow_id: "workflow-1",
  node_type: "image",
  semantic_role: "product",
  role_contract_version: "ad-media-role-v1",
  title: "Product hero",
  status: "ready",
  summary_prompt: "Premium product",
  generation_prompt: "Original product prompt",
  structured_content: {},
  model_id: "image-model-v1",
  parameters: { aspect_ratio: "1:1" },
  prompt_context_snapshot_id: "snapshot-1",
  output_asset_id: "asset-source",
  video_skill_run_id: null,
  position: { x: 200, y: 120 },
  revision: 3,
  error: null,
  created_at: "2026-07-28T00:00:00Z",
  updated_at: "2026-07-28T00:00:00Z",
};

const sibling: CanvasNodeV2 = {
  ...source,
  node_id: "image-sibling",
  title: "Alternative product hero",
  status: "draft",
  generation_prompt: "Edited product prompt",
  model_id: "image-model-v2",
  parameters: { aspect_ratio: "3:4" },
  output_asset_id: null,
  position: { x: 264, y: 176 },
  revision: 1,
};

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 3,
  nodes: [source],
  bindings: [],
  assets: [],
};

vi.mock("../../../AppContextValue.ts", () => ({
  useApp: () => ({
    agentCanvasWorkflow: workflow,
    setAgentCanvasWorkflow,
    workspaceHydrated: true,
    workspaceRestoreError: null,
  }),
}));

import { useAgentCanvasSession } from "./useAgentCanvasSession.ts";

beforeEach(() => {
  vi.clearAllMocks();
  createAgentCanvasNode.mockResolvedValue({
    value: {
      workflow: {
        ...workflow,
        revision: 4,
        nodes: [source, sibling],
      },
      node: sibling,
      binding: null,
    },
    etag: '"workflow-1-r4"',
  });
});

describe("useAgentCanvasSession Ready media variation", () => {
  it("creates the edited sibling through the authoring queue and selects it", async () => {
    const draft: ReadyMediaVariationDraft = {
      title: "Alternative product hero",
      generationPrompt: "Edited product prompt",
      modelId: "image-model-v2",
      parameters: { aspect_ratio: "3:4" },
    };
    const { result } = renderHook(() => useAgentCanvasSession());

    let created: CanvasNodeV2 | null | undefined;
    await act(async () => {
      created = await result.current.actions.createSiblingDraft(source, draft);
    });

    expect(createAgentCanvasNode).toHaveBeenCalledWith("workflow-1", {
      node_type: "image",
      semantic_role: "product",
      role_contract_version: "ad-media-role-v1",
      title: "Alternative product hero",
      summary_prompt: "Premium product",
      generation_prompt: "Edited product prompt",
      structured_content: {},
      model_id: "image-model-v2",
      parameters: { aspect_ratio: "3:4" },
      position: { x: 264, y: 176 },
      clone_inputs_from_node_id: "image-source",
      video_skill_run_id: null,
    });
    expect(created).toEqual(sibling);
    expect(result.current.state.selectedNodeId).toBe("image-sibling");
    expect(setAgentCanvasWorkflow).toHaveBeenCalledOnce();

    const merge = setAgentCanvasWorkflow.mock.calls[0]?.[0] as (
      current: AgentCanvasWorkflowV2,
    ) => AgentCanvasWorkflowV2;
    expect(merge(workflow).nodes.map((node) => node.node_id))
      .toEqual(["image-source", "image-sibling"]);
  });
});
