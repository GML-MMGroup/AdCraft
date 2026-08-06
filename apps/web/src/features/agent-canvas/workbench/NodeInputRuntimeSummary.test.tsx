import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProviderInputManifestAuditV2,
} from "../../../types-v2.ts";
import { NodeInputRuntimeSummary } from "./NodeInputRuntimeSummary.tsx";

const node: CanvasNodeV2 = {
  node_id: "node-video-1",
  workflow_id: "workflow-1",
  node_type: "video",
  creative_role: "general_video",
  role_contract_version: "ad-media-role-v1",
  title: "Product video",
  status: "draft",
  summary_prompt: null,
  generation_prompt: "A product launch video.",
  structured_content: {},
  model_id: null,
  parameters: {},
  prompt_context_snapshot_id: null,
  output_asset_id: null,
  position: { x: 0, y: 0 },
  revision: 1,
  error: null,
  variation_draft: null,
  created_at: "2026-07-31T04:00:00Z",
  updated_at: "2026-07-31T04:00:00Z",
};

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 1,
  layout_revision: 1,
  nodes: [
    node,
    { ...node, node_id: "node-world-setting", node_type: "text", creative_role: "world_setting", title: "World Setting" },
    { ...node, node_id: "node-script-1", node_type: "script", creative_role: "script", title: "Narration" },
    { ...node, node_id: "node-image-1", node_type: "image", creative_role: "product", title: "Packshot" },
    { ...node, node_id: "node-scene-1", node_type: "image", creative_role: "scene", title: "Scene board" },
  ],
  bindings: [],
  assets: [{
    asset_id: "asset-image-1",
    project_id: "project-1",
    workflow_id: "workflow-1",
    media_type: "image",
    source_type: "generated",
    semantic_type: null,
    display_name: "Packshot output",
    mime_type: "image/png",
    status: "ready",
    size_bytes: 0,
    storage_key: null,
    preview_url: "/assets/asset-image-1",
    media_url: "/assets/asset-image-1",
    width: 1024,
    height: 1024,
    duration_seconds: null,
    checksum: "checksum-1",
    source_semantic_role: "product",
    source_node_id: "node-image-1",
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    quality_metadata: {},
    created_at: "2026-07-31T04:00:00Z",
  }],
};

const audit: ProviderInputManifestAuditV2 = {
  node_id: "node-video-1",
  input_manifest_id: "manifest-1",
  execution_id: "execution-1",
  node_run_id: "node-run-1",
  world_setting_inputs: [{
    binding_id: "binding-world-setting",
    source_node_id: "node-world-setting",
    source_node_revision: 2,
    required: true,
    display_order: 1,
    projection_audience: "video_director",
    projection_contract_version: "world-setting-projection-v1",
    projection_snapshot_id: "projection-snapshot-1",
    projection_mode: "fallback",
    warning_code: "world_setting_projection_fallback",
  }],
  text_inputs: [{
    binding_id: "binding-script",
    source_node_id: "node-script-1",
    snapshot_id: "snapshot-1",
    input_role: "text_context",
    required: true,
    display_order: 2,
  }],
  media_inputs: [{
    binding_id: "binding-image",
    source_node_id: "node-image-1",
    asset_id: "asset-image-1",
    media_type: "image",
    input_role: "image_reference",
    source_semantic_role: "product",
    transport_type: "https_url",
    required: false,
    display_order: 0,
  }],
  omitted_optional_inputs: [{
    binding_id: "binding-scene",
    source_node_id: "node-scene-1",
    reason_code: "source_not_ready",
  }],
};

describe("NodeInputRuntimeSummary", () => {
  it("shows the backend-resolved inputs in display order without provider values", () => {
    render(<NodeInputRuntimeSummary workflow={workflow} node={node} inputManifest={audit} />);

    const entries = screen.getAllByTestId("resolved-input");
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining("Packshot output"),
      expect.stringContaining("World Setting"),
      expect.stringContaining("Narration"),
    ]);
    expect(screen.getByText("World Setting is using a fallback projection for this run.")).toBeTruthy();
    expect(screen.getByText("Optional input unavailable: Scene board")).toBeTruthy();
    expect(screen.queryByText("https://must-not-be-stored.example/image.png")).toBeNull();
  });

  it("identifies source nodes that must become ready before the selected node can run", () => {
    render(
      <NodeInputRuntimeSummary
        workflow={workflow}
        node={node}
        inputReadinessIssue={{
          target_node_id: "node-video-1",
          source_node_ids: ["node-script-1", "node-image-1"],
        }}
      />,
    );

    expect(screen.getByText("Waiting for required inputs: Narration, Packshot")).toBeTruthy();
  });
});
