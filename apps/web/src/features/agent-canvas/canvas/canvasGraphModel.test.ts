import { describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  CanvasRuntimeSnapshotV2,
} from "../../../types-v2.ts";
import {
  findAvailableCanvasPosition,
  needsInitialCanvasLayout,
  highlightNodeRelatedCanvasEdges,
  inputRoleForSourceNode,
  incrementalPlacementForNodes,
  reconcileSelectableCanvasEdges,
  toAgentCanvasFlowEdges,
  toAgentCanvasFlowNodes,
} from "./canvasGraphModel.ts";

function node(nodeId: string, nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: creativeRoleForNodeType(nodeType),
    role_contract_version: "ad-media-role-v1",
    title: nodeId,
    status: "draft",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: nodeType === "image" ? "asset-1" : null,
    position: { x: 40, y: 60 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

function creativeRoleForNodeType(nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2["creative_role"] {
  switch (nodeType) {
    case "text":
      return "general_text";
    case "script":
      return "script";
    case "image":
      return "general_image";
    case "video":
      return "general_video";
    case "audio":
      return "general_audio";
    case "editing":
      return "editing";
  }
}

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 3,
  layout_revision: 1,
  nodes: [node("image-1", "image"), node("video-1", "video")],
  bindings: [{
    binding_id: "binding-1",
    workflow_id: "workflow-1",
    source: { kind: "node_output", source_node_id: "image-1" },
    target_node_id: "video-1",
    input_role: "image_reference",
    required: true,
    enabled: true,
    order: 0,
    label: null,
    metadata: {},
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  }],
  assets: [{
    asset_id: "asset-1",
    project_id: "project-1",
    workflow_id: "workflow-1",
    media_type: "image",
    source_type: "generated",
    display_name: "Frame",
    mime_type: "image/webp",
    status: "ready",
    size_bytes: 0,
    storage_key: null,
    preview_url: "/frame.webp",
    media_url: "/frame.webp",
    width: 1024,
    height: 1024,
    duration_seconds: null,
    checksum: "frame",
    source_semantic_role: null,
    source_node_id: "image-1",
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    quality_metadata: {},
    created_at: "2026-07-28T00:00:00Z",
  }],
};

const runtime: CanvasRuntimeSnapshotV2 = {
  workflow_id: "workflow-1",
  active_execution_id: "execution-1",
  execution_status: "running",
  node_runtime: {
    "image-1": {
      node_id: "image-1",
      visible_status: "working",
      phase: "running",
      execution_id: "execution-1",
      provider_task_id: null,
      waiting_for_node_ids: [],
      blocked_by_node_ids: [],
      attempt_no: 1,
      updated_at: "2026-07-28T00:00:01Z",
      error: null,
    },
  },
  queued_node_ids: [],
  working_node_ids: ["image-1"],
  waiting_node_ids: [],
  ready_node_ids: [],
  failed_node_ids: [],
  events_cursor: 2,
  updated_at: "2026-07-28T00:00:01Z",
};

describe("canvasGraphModel", () => {
  it("detects collapsed persisted positions without rearranging a single or already separated node", () => {
    expect(needsInitialCanvasLayout([
      { ...node("first", "image"), position: { x: 0, y: 0 } },
      { ...node("second", "video"), position: { x: 0, y: 0 } },
    ])).toBe(true);

    expect(needsInitialCanvasLayout([
      { ...node("first", "image"), position: { x: 0, y: 0 } },
      { ...node("second", "video"), position: { x: 320, y: 0 } },
    ])).toBe(false);
    expect(needsInitialCanvasLayout([
      { ...node("only", "image"), position: { x: 0, y: 0 } },
    ])).toBe(false);
  });

  it("maps canonical nodes, assets and node runtime directly into React Flow data", () => {
    const nodes = toAgentCanvasFlowNodes(workflow, runtime, {
      onRun: vi.fn(),
      onRetry: vi.fn(),
      onExport: vi.fn(),
    });

    expect(nodes).toHaveLength(2);
    expect(nodes[0]).toMatchObject({
      id: "image-1",
      type: "agentCanvas",
      position: { x: 40, y: 60 },
      style: { width: 310, height: 310 },
      data: {
        node: { node_id: "image-1" },
        asset: { asset_id: "asset-1" },
        runtime: { visible_status: "working" },
      },
    });
  });

  it("reuses unchanged flow node and data objects across canonical refreshes", () => {
    const callbacks = {
      onOpenVideoPreview: vi.fn(),
      renderWorkbench: vi.fn(),
    };
    const first = toAgentCanvasFlowNodes(workflow, runtime, callbacks);
    const refreshedWorkflow = {
      ...workflow,
      nodes: workflow.nodes.map((item) => ({ ...item })),
      assets: workflow.assets.map((item) => ({ ...item })),
    };
    const refreshedRuntime = {
      ...runtime,
      node_runtime: Object.fromEntries(Object.entries(runtime.node_runtime).map(([nodeId, item]) => [
        nodeId,
        { ...item },
      ])),
    };

    const refreshed = toAgentCanvasFlowNodes(
      refreshedWorkflow,
      refreshedRuntime,
      { ...callbacks, renderWorkbench: vi.fn() },
      { previousNodes: first, activeWorkbenchNodeId: null },
    );

    expect(refreshed[0]).toBe(first[0]);
    expect(refreshed[0]?.data).toBe(first[0]?.data);
    expect(refreshed[1]).toBe(first[1]);
  });

  it("projects conversation-source availability and rebuilds only nodes whose source changes", () => {
    const callbacks = { onShowInConversation: vi.fn() };
    const first = toAgentCanvasFlowNodes(workflow, runtime, callbacks, {
      conversationSourceNodeIds: new Set(["image-1"]),
    });
    const refreshed = toAgentCanvasFlowNodes(workflow, runtime, callbacks, {
      previousNodes: first,
      conversationSourceNodeIds: new Set(["video-1"]),
    });

    expect(first[0]?.data.conversationSourceAvailable).toBe(true);
    expect(first[1]?.data.conversationSourceAvailable).toBe(false);
    expect(refreshed[0]).not.toBe(first[0]);
    expect(refreshed[1]).not.toBe(first[1]);
    expect(refreshed[0]?.data.conversationSourceAvailable).toBe(false);
    expect(refreshed[1]?.data.conversationSourceAvailable).toBe(true);
  });

  it("keeps the last media asset while a canonical refresh temporarily omits it", () => {
    const first = toAgentCanvasFlowNodes(workflow, runtime, {});
    const refreshed = toAgentCanvasFlowNodes(
      { ...workflow, assets: [] },
      runtime,
      {},
      { previousNodes: first },
    );

    expect(refreshed[0]?.data.asset).toBe(first[0]?.data.asset);
    expect(refreshed[0]?.data.asset?.asset_id).toBe("asset-1");
  });

  it("does not keep stale media when the node points to a different asset", () => {
    const first = toAgentCanvasFlowNodes(workflow, runtime, {});
    const changedWorkflow = {
      ...workflow,
      nodes: workflow.nodes.map((item) => item.node_id === "image-1"
        ? { ...item, output_asset_id: "asset-2" }
        : item),
      assets: [],
    };

    const refreshed = toAgentCanvasFlowNodes(
      changedWorkflow,
      runtime,
      {},
      { previousNodes: first },
    );

    expect(refreshed[0]?.data.asset).toBeNull();
  });

  it("does not keep the previous version when the asset version changes", () => {
    const first = toAgentCanvasFlowNodes(workflow, runtime, {});
    const changedAsset = {
      ...workflow.assets[0]!,
      version_id: "asset-version-2",
      preview_url: null,
      media_url: null,
    };
    const refreshed = toAgentCanvasFlowNodes(
      { ...workflow, assets: [changedAsset] },
      runtime,
      {},
      { previousNodes: first },
    );

    expect(refreshed[0]?.data.asset).toBe(changedAsset);
  });

  it("rebuilds only the changed node and the active workbench node", () => {
    const firstWorkbench = vi.fn();
    const first = toAgentCanvasFlowNodes(workflow, runtime, {
      renderWorkbench: firstWorkbench,
    });
    const changedWorkflow = {
      ...workflow,
      nodes: workflow.nodes.map((item, index) => index === 0
        ? { ...item, revision: item.revision + 1 }
        : { ...item }),
    };

    const refreshed = toAgentCanvasFlowNodes(
      changedWorkflow,
      runtime,
      { renderWorkbench: vi.fn() },
      { previousNodes: first, activeWorkbenchNodeId: "video-1" },
    );

    expect(refreshed[0]).not.toBe(first[0]);
    expect(refreshed[1]).not.toBe(first[1]);
  });

  it("does not reuse matching node ids across workflows", () => {
    const first = toAgentCanvasFlowNodes(workflow, runtime, {});
    const otherWorkflow = {
      ...workflow,
      workflow_id: "workflow-2",
      nodes: workflow.nodes.map((item) => ({ ...item, workflow_id: "workflow-2" })),
    };
    const refreshed = toAgentCanvasFlowNodes(
      otherWorkflow,
      null,
      {},
      { previousNodes: first },
    );

    expect(refreshed[0]).not.toBe(first[0]);
  });

  it("keeps canonical node dimensions and data independent from viewport focus", () => {
    const focusedWorkflow = {
      ...workflow,
      assets: [{ ...workflow.assets[0]!, width: 1920, height: 1080 }],
    };

    const nodes = toAgentCanvasFlowNodes(focusedWorkflow, null, {});
    const imageNode = nodes.find((item) => item.id === "image-1");

    expect(imageNode?.style).toEqual({ width: 360, height: 203 });
    expect(imageNode?.data).not.toHaveProperty("focused");
  });

  it("renders Script nodes and their persisted text-context bindings", () => {
    const script = node("script-1", "script");
    const workflowWithScript: AgentCanvasWorkflowV2 = {
      ...workflow,
      nodes: [workflow.nodes[0]!, script, workflow.nodes[1]!],
      bindings: [
        workflow.bindings[0]!,
        {
          ...workflow.bindings[0]!,
          binding_id: "binding-to-script",
          target_node_id: script.node_id,
        },
        {
          ...workflow.bindings[0]!,
          binding_id: "binding-from-script",
          source: { kind: "node_output", source_node_id: script.node_id },
        },
      ],
    };

    expect(toAgentCanvasFlowNodes(workflowWithScript, null, {}).map((item) => item.id))
      .toEqual(["image-1", "script-1", "video-1"]);
    expect(toAgentCanvasFlowEdges(workflowWithScript.bindings, workflowWithScript.nodes))
      .toEqual([
        expect.objectContaining({ id: "binding-1" }),
        expect.objectContaining({ id: "binding-to-script" }),
        expect.objectContaining({ id: "binding-from-script" }),
      ]);
  });

  it("leaves React Flow dimensions measurable when image metadata is unavailable", () => {
    const withoutDimensions = {
      ...workflow,
      assets: [{ ...workflow.assets[0]!, width: null, height: null }],
    };

    const nodes = toAgentCanvasFlowNodes(withoutDimensions, null, {});

    expect(nodes.find((item) => item.id === "image-1")?.style).toBeUndefined();
  });

  it("renders only backend bindings as edges", () => {
    const edges = toAgentCanvasFlowEdges(workflow.bindings, workflow.nodes);

    expect(edges).toEqual([expect.objectContaining({
      id: "binding-1",
      source: "image-1",
      target: "video-1",
      type: "default",
    })]);
    expect(edges[0]?.style).toBeUndefined();
    expect(edges[0]?.markerEnd).toMatchObject({
      color: "rgba(229, 231, 238, 0.72)",
    });
  });

  it("preserves selected bindings while reconciling canonical backend edges", () => {
    const canonical = toAgentCanvasFlowEdges(workflow.bindings, workflow.nodes);
    const selected = canonical.map((edge) => ({ ...edge, selected: true }));

    expect(reconcileSelectableCanvasEdges(canonical, selected)).toEqual([
      expect.objectContaining({ id: "binding-1", selected: true }),
    ]);
  });

  it("drops selection state for bindings that no longer exist", () => {
    const staleSelectedEdge = {
      id: "deleted-binding",
      source: "image-1",
      target: "video-1",
      selected: true,
    };

    expect(reconcileSelectableCanvasEdges([], [staleSelectedEdge])).toEqual([]);
  });

  it("visually highlights only edges directly related to the selected node", () => {
    const baseEdges = [
      { id: "incoming", source: "image-1", target: "video-1" },
      { id: "outgoing", source: "video-1", target: "editing-1" },
      { id: "unrelated", source: "audio-1", target: "editing-1" },
    ];

    expect(highlightNodeRelatedCanvasEdges(baseEdges, "video-1")).toEqual([
      expect.objectContaining({ id: "incoming", className: "is-node-related" }),
      expect.objectContaining({ id: "outgoing", className: "is-node-related" }),
      expect.not.objectContaining({ className: "is-node-related" }),
    ]);
  });

  it("does not select related edges or retain their highlight after node deselection", () => {
    const related = highlightNodeRelatedCanvasEdges([
      { id: "binding-1", source: "image-1", target: "video-1" },
    ], "video-1");

    expect(related[0]?.selected).not.toBe(true);
    expect(highlightNodeRelatedCanvasEdges(related, null)[0]).not.toHaveProperty("className");
  });

  it("does not render disabled or asset-backed bindings as inferred edges", () => {
    expect(toAgentCanvasFlowEdges([
      { ...workflow.bindings[0]!, enabled: false },
      {
        ...workflow.bindings[0]!,
        binding_id: "asset-binding",
        source: { kind: "image_asset", source_asset_id: "asset-1" },
      },
    ], workflow.nodes)).toEqual([]);
  });

  it("renders a persisted World Setting binding and removes it when disabled", () => {
    const binding = {
      ...workflow.bindings[0]!,
      binding_id: "binding-world-setting",
      source: { kind: "node_output" as const, source_node_id: "node-world-setting" },
      target_node_id: "video-1",
      input_role: "text_context" as const,
      metadata: { context_kind: "world_setting" },
    };

    const nodes = [
      { ...node("node-world-setting", "text"), creative_role: "world_setting" as const },
      workflow.nodes[1]!,
    ];

    expect(toAgentCanvasFlowEdges([binding], nodes)).toEqual([expect.objectContaining({
      id: "binding-world-setting",
      source: "node-world-setting",
      target: "video-1",
    })]);
    expect(toAgentCanvasFlowEdges([{ ...binding, enabled: false }], nodes)).toEqual([]);
  });

  it("selects explicit input roles from canonical source node media types", () => {
    expect(inputRoleForSourceNode(node("brief", "text"))).toBe("text_context");
    expect(inputRoleForSourceNode(node("script", "script"))).toBe("text_context");
    expect(inputRoleForSourceNode(node("image", "image"))).toBe("image_reference");
    expect(inputRoleForSourceNode(node("video", "video"))).toBe("video_reference");
    expect(inputRoleForSourceNode(node("audio", "audio"))).toBe("audio_reference");
    expect(inputRoleForSourceNode(node("editing", "editing"))).toBe("video_reference");
  });

  it("places a new node near the preferred point without overlapping existing cards", () => {
    const existing = [
      { ...node("center", "image"), position: { x: 100, y: 100 } },
      { ...node("right", "video"), position: { x: 440, y: 100 } },
    ];

    expect(findAvailableCanvasPosition(existing, { x: 100, y: 100 })).toEqual({
      x: -240,
      y: 100,
    });
  });

  it("reserves the tall Script card footprint when placing a new node", () => {
    const script = { ...node("script", "script"), position: { x: 100, y: 100 } };

    expect(findAvailableCanvasPosition(
      [script],
      { x: 100, y: 100 },
      { candidateNodeType: "image" },
    )).toEqual({ x: 416, y: 100 });
  });

  it("uses adaptive image rectangles when placing a node beside generated media", () => {
    const landscape = { ...node("landscape", "image"), position: { x: 100, y: 100 } };
    const landscapeAsset = {
      ...workflow.assets[0]!,
      asset_id: "landscape-asset",
      width: 1920,
      height: 1080,
    };
    landscape.output_asset_id = landscapeAsset.asset_id;

    expect(findAvailableCanvasPosition(
      [landscape],
      { x: 100, y: 100 },
      {
        assets: [landscapeAsset],
        candidateNodeType: "image",
        candidateDimensions: { width: 1080, height: 1920 },
      },
    )).toEqual({
      x: -171,
      y: 100,
    });
  });

  it("reserves enough layout space for an image whose intrinsic dimensions have not loaded", () => {
    const unresolvedImage = {
      ...node("unresolved", "image"),
      output_asset_id: null,
      position: { x: 100, y: 100 },
    };

    expect(findAvailableCanvasPosition(
      [unresolvedImage],
      { x: 440, y: 100 },
      { candidateNodeType: "video" },
    )).toEqual({
      x: 528,
      y: 100,
    });
  });

  it("places only newly created nodes from backend placement hints", () => {
    const source = { ...node("source", "image"), position: { x: 100, y: 100 } };
    const unrelated = { ...node("unrelated", "video"), position: { x: 460, y: 100 } };
    const sibling = { ...node("sibling", "image"), position: { x: 460, y: 100 } };

    const positions = incrementalPlacementForNodes(
      [source, unrelated, sibling],
      ["sibling"],
      [{
        intent: "right_sibling",
        anchor_node_id: "source",
        group_key: null,
      }],
      { x: 200, y: 200 },
    );

    expect(positions).toEqual([
      { node_id: "sibling", x: 800, y: 100 },
    ]);
    expect(source.position).toEqual({ x: 100, y: 100 });
    expect(unrelated.position).toEqual({ x: 460, y: 100 });
  });

  it("keeps sibling-only Working state when the generated variation runs", () => {
    const source = {
      ...node("source", "image"),
      status: "ready" as const,
      output_asset_id: "asset-source",
    };
    const sibling = node("sibling", "image");
    const variationWorkflow = {
      ...workflow,
      nodes: [source, sibling],
      assets: [{
        ...workflow.assets[0]!,
        asset_id: "asset-source",
      }],
    };
    const variationRuntime: CanvasRuntimeSnapshotV2 = {
      ...runtime,
      node_runtime: {
        sibling: {
          ...runtime.node_runtime["image-1"]!,
          node_id: "sibling",
        },
      },
      working_node_ids: ["sibling"],
    };

    const nodes = toAgentCanvasFlowNodes(variationWorkflow, variationRuntime, {
      onRun: vi.fn(),
      onRetry: vi.fn(),
      onExport: vi.fn(),
    });

    expect(nodes.find((item) => item.id === "source")?.data.runtime).toBeNull();
    expect(nodes.find((item) => item.id === "source")?.data.node.status).toBe("ready");
    expect(nodes.find((item) => item.id === "sibling")?.data.runtime?.visible_status).toBe("working");
  });
});
