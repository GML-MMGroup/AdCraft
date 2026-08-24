import { describe, expect, it } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasBindingV2,
  CanvasBindingMutationResponseV2,
  CanvasConnectedNodeCreateResponseV2,
  CanvasEditingExportImportResponseV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import {
  mergeAgentCanvasLayout,
  mergeAgentCanvasBindingMutation,
  mergeAgentCanvasConnectedNode,
  mergeAgentCanvasEditingExportImport,
  mergeAgentCanvasNode,
  mergeAgentCanvasWorkflow,
  overlayAgentCanvasPositions,
} from "./workflowMerge.ts";

function node(
  overrides: Partial<CanvasNodeV2> = {},
): CanvasNodeV2 {
  return {
    node_id: "node-image",
    workflow_id: "workflow-1",
    node_type: "image",
    creative_role: "character",
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
    position: { x: 120, y: 80 },
    revision: 2,
    error: null,
    variation_draft: null,
    created_at: "2026-07-28T10:00:00Z",
    updated_at: "2026-07-28T10:01:00Z",
    ...overrides,
  };
}

const publishedAsset: ProjectAssetSummaryV2 = {
  asset_id: "asset-generated",
  project_id: "project-1",
  workflow_id: "workflow-1",
  media_type: "image",
  source_type: "generated",
  display_name: "Character",
  mime_type: "image/png",
  status: "ready",
  size_bytes: 0,
  storage_key: null,
  preview_url: "/assets/character.png",
  media_url: "/assets/character.png",
  width: 1024,
  height: 1024,
  duration_seconds: null,
  checksum: "generated",
  source_semantic_role: "character",
  source_node_id: "node-image",
  source_execution_id: null,
  provider: null,
  model_id: null,
  prompt_provenance: {},
  quality_metadata: {},
  created_at: "2026-07-28T10:05:00Z",
};

const binding: CanvasBindingV2 = {
  binding_id: "binding-1",
  workflow_id: "workflow-1",
  source: { kind: "node_output", source_node_id: "node-image" },
  target_node_id: "node-video",
  input_role: "image_reference",
  required: true,
  enabled: true,
  order: 0,
  label: null,
  metadata: {},
  created_at: "2026-07-28T10:05:00Z",
  updated_at: "2026-07-28T10:05:00Z",
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
    layout_revision: 1,
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

  it("accepts newer semantic data without regressing a newer local layout", () => {
    const current = workflow({
      layout_revision: 3,
      nodes: [node({ position: { x: 410, y: 220 } })],
    });
    const refreshed = workflow({
      revision: 5,
      layout_revision: 2,
      nodes: [node({ position: { x: 150, y: 90 } })],
    });

    expect(mergeAgentCanvasWorkflow(current, refreshed)).toMatchObject({
      revision: 5,
      layout_revision: 3,
      nodes: [{ position: { x: 410, y: 220 } }],
    });
  });

  it("accepts newer layout positions without regressing semantic state", () => {
    const current = workflow({
      revision: 7,
      layout_revision: 2,
      nodes: [node({
        status: "ready",
        output_asset_id: publishedAsset.asset_id,
        position: { x: 410, y: 220 },
        revision: 5,
      })],
      assets: [publishedAsset],
    });
    const layoutRefresh = workflow({
      revision: 6,
      layout_revision: 3,
      nodes: [node({
        status: "working",
        position: { x: 820, y: 360 },
        revision: 4,
      })],
    });

    expect(mergeAgentCanvasWorkflow(current, layoutRefresh)).toMatchObject({
      revision: 7,
      layout_revision: 3,
      nodes: [{
        status: "ready",
        output_asset_id: publishedAsset.asset_id,
        position: { x: 820, y: 360 },
      }],
    });
  });

  it("applies layout responses without advancing semantic revision or accepting stale positions", () => {
    const current = workflow({
      revision: 4,
      layout_revision: 3,
      nodes: [node({ position: { x: 10, y: 20 } })],
    });
    const stale = mergeAgentCanvasLayout(current, {
      workflow_id: current.workflow_id,
      revision: 99,
      layout_revision: 2,
      positions: [{ node_id: "node-image", x: 500, y: 600 }],
    });
    expect(stale).toBe(current);

    const next = mergeAgentCanvasLayout(current, {
      workflow_id: current.workflow_id,
      revision: 99,
      layout_revision: 4,
      positions: [{ node_id: "node-image", x: 140, y: 260 }],
    });
    expect(next.revision).toBe(4);
    expect(next.layout_revision).toBe(4);
    expect(next.nodes[0]?.position).toEqual({ x: 140, y: 260 });
  });

  it("keeps a newer optimistic position over an earlier in-flight layout response", () => {
    const current = workflow({
      layout_revision: 3,
      nodes: [node({ position: { x: 140, y: 260 } })],
    });
    const withPending = overlayAgentCanvasPositions(current, [{
      node_id: "node-image",
      x: 720,
      y: 480,
    }]);

    expect(withPending.layout_revision).toBe(3);
    expect(withPending.nodes[0]?.position).toEqual({ x: 720, y: 480 });
  });
});

describe("mergeAgentCanvasEditingExportImport", () => {
  it("adopts the authoritative imported node, binding, asset, and revisions on replay", () => {
    const importedNode = node({
      node_id: "video-export",
      node_type: "video",
      creative_role: "general_video",
      status: "ready",
      execution_mode: "source_only",
      output_asset_id: "asset-export",
      position: { x: 520, y: 80 },
    });
    const importedBinding: CanvasBindingV2 = {
      ...binding,
      binding_id: "binding-editing-export",
      source: { kind: "node_output", source_node_id: "editing-1" },
      target_node_id: importedNode.node_id,
      input_role: "video_reference",
    };
    const importedAsset: ProjectAssetSummaryV2 = {
      ...publishedAsset,
      asset_id: "asset-export",
      media_type: "video",
      source_type: "editing_export",
      display_name: "Final cut source",
      media_url: "/api/v2/assets/asset-export/content",
      preview_url: "/api/v2/assets/asset-export/content",
      source_semantic_role: null,
      source_node_id: "video-export",
    };
      const response: CanvasEditingExportImportResponseV2 = {
        workflow_id: "workflow-1",
        revision: 9,
      layout_revision: 4,
      node: importedNode,
      binding: importedBinding,
      asset: importedAsset,
      events_cursor: 41,
      replayed: true,
    };
    const current = workflow({
      revision: 8,
      layout_revision: 3,
      nodes: [node({ node_id: "editing-1", node_type: "editing", creative_role: "editing" }), importedNode],
      bindings: [importedBinding],
      assets: [importedAsset],
    });

    const merged = mergeAgentCanvasEditingExportImport(current, response);

    expect(merged.revision).toBe(9);
    expect(merged.layout_revision).toBe(4);
    expect(merged.nodes.filter((item) => item.node_id === importedNode.node_id)).toHaveLength(1);
    expect(merged.bindings.filter((item) => item.binding_id === importedBinding.binding_id)).toHaveLength(1);
    expect(merged.assets.filter((item) => item.asset_id === importedAsset.asset_id)).toHaveLength(1);
    expect(merged.nodes.find((item) => item.node_id === importedNode.node_id)).toBe(importedNode);
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

describe("semantic mutation merges", () => {
  it("adds an atomically connected node and its persisted binding", () => {
    const response: CanvasConnectedNodeCreateResponseV2 = {
      workflow_id: "workflow-1",
      revision: 5,
      layout_revision: 2,
      node: node({
        node_id: "node-video",
        node_type: "video",
        creative_role: "general_video",
        position: { x: 460, y: 80 },
      }),
      binding,
      events_cursor: 7,
    };

    const next = mergeAgentCanvasConnectedNode(workflow(), response);

    expect(next.revision).toBe(5);
    expect(next.layout_revision).toBe(2);
    expect(next.nodes.map((item) => item.node_id)).toContain("node-video");
    expect(next.bindings).toContainEqual(binding);
  });

  it("replaces the target node's incoming bindings after a binding patch", () => {
    const optional = { ...binding, required: false, enabled: false, order: 2 };
    const response: CanvasBindingMutationResponseV2 = {
      workflow_id: "workflow-1",
      revision: 6,
      binding: optional,
      incoming_bindings: [optional],
      events_cursor: 8,
    };

    const next = mergeAgentCanvasBindingMutation(
      workflow({
        bindings: [
          binding,
          { ...binding, binding_id: "unrelated", target_node_id: "node-other" },
        ],
      }),
      response,
    );

    expect(next.revision).toBe(6);
    expect(next.bindings.find((item) => item.binding_id === "binding-1")).toEqual(optional);
    expect(next.bindings.find((item) => item.binding_id === "unrelated")).toBeTruthy();
  });
});
