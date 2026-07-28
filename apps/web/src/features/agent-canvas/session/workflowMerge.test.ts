import { describe, expect, it } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import {
  mergeAgentCanvasNode,
  mergeAgentCanvasWorkflow,
} from "./workflowMerge.ts";

function node(
  overrides: Partial<CanvasNodeV2> = {},
): CanvasNodeV2 {
  return {
    node_id: "node-image",
    workflow_id: "workflow-1",
    node_type: "image",
    semantic_role: "character_main",
    role_contract_version: "ad-media-role-v1",
    title: "Character",
    status: "working",
    summary_prompt: null,
    generation_prompt: "Create a character",
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    video_skill_run_id: null,
    position: { x: 120, y: 80 },
    revision: 2,
    error: null,
    created_at: "2026-07-28T10:00:00Z",
    updated_at: "2026-07-28T10:01:00Z",
    ...overrides,
  };
}

const publishedAsset: ProjectAssetSummaryV2 = {
  asset_id: "asset-generated",
  media_type: "image",
  source_type: "generated",
  display_name: "Character",
  mime_type: "image/png",
  status: "ready",
  preview_url: "/assets/character.png",
  media_url: "/assets/character.png",
  width: 1024,
  height: 1024,
  duration_seconds: null,
  checksum: "generated",
};

function workflow(
  overrides: Partial<AgentCanvasWorkflowV2> = {},
): AgentCanvasWorkflowV2 {
  return {
    workflow_id: "workflow-1",
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 4,
    nodes: [node()],
    bindings: [],
    assets: [],
    ...overrides,
  };
}

describe("mergeAgentCanvasWorkflow", () => {
  it("keeps runtime publication and optimistic position from a newer same-revision state", () => {
    const current = workflow({
      nodes: [node({
        status: "ready",
        output_asset_id: publishedAsset.asset_id,
        position: { x: 720, y: 360 },
      })],
      assets: [publishedAsset],
    });
    const staleRefresh = workflow({
      nodes: [node({
        status: "working",
        position: { x: 120, y: 80 },
        revision: 2,
        updated_at: "2026-07-28T10:01:00Z",
      })],
    });

    const merged = mergeAgentCanvasWorkflow(current, staleRefresh);

    expect(merged.nodes[0]).toMatchObject({
      status: "ready",
      output_asset_id: publishedAsset.asset_id,
      position: { x: 720, y: 360 },
    });
    expect(merged.assets).toContainEqual(publishedAsset);
  });

  it("accepts newer node data on the same workflow revision without losing local position", () => {
    const current = workflow({
      nodes: [node({ position: { x: 410, y: 220 } })],
    });
    const refreshed = workflow({
      nodes: [node({
        status: "ready",
        output_asset_id: publishedAsset.asset_id,
        revision: 3,
        updated_at: "2026-07-28T10:04:00Z",
      })],
      assets: [publishedAsset],
    });

    const merged = mergeAgentCanvasWorkflow(current, refreshed);

    expect(merged.nodes[0]).toMatchObject({
      status: "ready",
      output_asset_id: publishedAsset.asset_id,
      position: { x: 410, y: 220 },
    });
  });

  it("replaces the document when the backend workflow revision advances", () => {
    const current = workflow({
      nodes: [node({ position: { x: 410, y: 220 } })],
    });
    const refreshed = workflow({
      revision: 5,
      nodes: [node({ position: { x: 150, y: 90 } })],
    });

    expect(mergeAgentCanvasWorkflow(current, refreshed)).toBe(refreshed);
  });
});

describe("mergeAgentCanvasNode", () => {
  it("does not regress a runtime-enriched node and keeps its optimistic position", () => {
    const current = node({
      status: "ready",
      output_asset_id: publishedAsset.asset_id,
      position: { x: 510, y: 240 },
      revision: 4,
      updated_at: "2026-07-28T10:05:00Z",
    });
    const stale = node({
      status: "working",
      revision: 3,
      updated_at: "2026-07-28T10:04:00Z",
    });

    expect(mergeAgentCanvasNode(current, stale)).toMatchObject({
      status: "ready",
      output_asset_id: publishedAsset.asset_id,
      position: { x: 510, y: 240 },
    });
  });
});
