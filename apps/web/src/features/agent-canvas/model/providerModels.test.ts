import { describe, expect, it } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import {
  providerInputTypes,
  providerOutputType,
  runnableDraftParameterMigrations,
  usesMediaProvider,
  usesProvider,
} from "./providerModels.ts";

function node(nodeId: string, nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: nodeType === "text" ? "general_text" : nodeType === "script" ? "script" : nodeType === "image" ? "general_image" : nodeType === "video" ? "general_video" : nodeType === "audio" ? "general_audio" : "editing",
    role_contract_version: "ad-media-role-v1",
    title: nodeType,
    status: "ready",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: nodeType === "image" || nodeType === "video" || nodeType === "audio"
      ? `${nodeId}-asset`
      : null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

describe("providerInputTypes", () => {
  it("derives the complete provider input set from node and image-asset bindings", () => {
    const workflow: AgentCanvasWorkflowV2 = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 3,
      layout_revision: 1,
      nodes: [
        node("script-1", "script"),
        node("video-1", "video"),
        { ...node("target-1", "video"), status: "draft", output_asset_id: null },
      ],
      bindings: [
        {
          binding_id: "binding-script",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: "script-1" },
          target_node_id: "target-1",
          input_role: "text_context",
          required: true,
          enabled: true,
          order: 0,
          label: null,
          metadata: {},
          created_at: "2026-07-28T00:00:00Z",
          updated_at: "2026-07-28T00:00:00Z",
        },
        {
          binding_id: "binding-video",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: "video-1" },
          target_node_id: "target-1",
          input_role: "video_reference",
          required: false,
          enabled: true,
          order: 1,
          label: null,
          metadata: {},
          created_at: "2026-07-28T00:00:00Z",
          updated_at: "2026-07-28T00:00:00Z",
        },
        {
          binding_id: "binding-image",
          workflow_id: "workflow-1",
          source: { kind: "image_asset", source_asset_id: "asset-reference" },
          target_node_id: "target-1",
          input_role: "image_reference",
          required: false,
          enabled: true,
          order: 2,
          label: null,
          metadata: {},
          created_at: "2026-07-28T00:00:00Z",
          updated_at: "2026-07-28T00:00:00Z",
        },
      ],
      assets: [],
    };

    expect(providerInputTypes(workflow, "target-1")).toEqual(["image", "text", "video"]);
  });

  it("derives Script inputs without treating Script as a provider capability output", () => {
    const workflow = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 3,
      layout_revision: 1,
      nodes: [
        node("text-1", "text"),
        node("image-1", "image"),
        node("video-1", "video"),
        node("audio-1", "audio"),
        { ...node("target-1", "script"), status: "draft", output_asset_id: null },
      ],
      bindings: [
        {
          binding_id: "text-input",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: "text-1" },
          target_node_id: "target-1",
          input_role: "text_context",
          required: true,
          enabled: true,
          order: 0,
          label: null,
          metadata: {},
          created_at: "2026-07-30T00:00:00Z",
          updated_at: "2026-07-30T00:00:00Z",
        },
        {
          binding_id: "image-input",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: "image-1" },
          target_node_id: "target-1",
          input_role: "image_reference",
          required: false,
          enabled: true,
          order: 1,
          label: null,
          metadata: {},
          created_at: "2026-07-30T00:00:00Z",
          updated_at: "2026-07-30T00:00:00Z",
        },
        {
          binding_id: "disabled-video-input",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: "video-1" },
          target_node_id: "target-1",
          input_role: "video_reference",
          required: false,
          enabled: false,
          order: 2,
          label: null,
          metadata: {},
          created_at: "2026-07-30T00:00:00Z",
          updated_at: "2026-07-30T00:00:00Z",
        },
        {
          binding_id: "audio-input",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: "audio-1" },
          target_node_id: "target-1",
          input_role: "audio_reference",
          required: false,
          enabled: true,
          order: 3,
          label: null,
          metadata: {},
          created_at: "2026-07-30T00:00:00Z",
          updated_at: "2026-07-30T00:00:00Z",
        },
      ],
      assets: [],
    } as unknown as AgentCanvasWorkflowV2;
    const script = workflow.nodes.find((candidate) => candidate.node_id === "target-1")!;

    expect(usesProvider(script)).toBe(false);
    expect(usesMediaProvider(script)).toBe(false);
    expect(providerOutputType(script)).toBeNull();
    expect(providerInputTypes(workflow, script.node_id)).toEqual(["audio", "image", "text"]);
  });

  it("limits provider capability output types to media nodes", () => {
    const expectedOutputs: Array<[
      CanvasNodeV2["node_type"],
      "image" | "video" | "audio" | null,
    ]> = [
      ["text", null],
      ["script", null],
      ["image", "image"],
      ["video", "video"],
      ["audio", "audio"],
      ["editing", null],
    ];

    expectedOutputs.forEach(([nodeType, outputType]) => {
      const candidate = node(`node-${nodeType}`, nodeType);
      expect(usesMediaProvider(candidate)).toBe(outputType !== null);
      expect(providerOutputType(candidate)).toBe(outputType);
    });
  });

  it("collects canonical duration migrations only for runnable Draft video nodes", () => {
    const workflow: AgentCanvasWorkflowV2 = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 3,
      layout_revision: 1,
      nodes: [
        {
          ...node("video-zero", "video"),
          status: "draft",
          output_asset_id: null,
          parameters: {
            requested_duration_seconds: 0,
            effective_duration_seconds: 15,
          },
        },
        {
          ...node("video-thirty", "video"),
          status: "draft",
          output_asset_id: null,
          parameters: { requested_duration_seconds: 30 },
        },
        {
          ...node("video-ready", "video"),
          parameters: { requested_duration_seconds: 12 },
        },
        {
          ...node("image-draft", "image"),
          status: "draft",
          output_asset_id: null,
          parameters: { requested_duration_seconds: 12 },
        },
      ],
      bindings: [],
      assets: [],
    };

    expect(runnableDraftParameterMigrations(workflow)).toEqual([
      { node_id: "video-zero", parameters: {} },
      { node_id: "video-thirty", parameters: { duration_seconds: 30 } },
    ]);
  });
});
