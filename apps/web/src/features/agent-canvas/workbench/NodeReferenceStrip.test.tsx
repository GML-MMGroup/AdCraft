import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import { NodeReferenceStrip } from "./NodeReferenceStrip.tsx";

const node: CanvasNodeV2 = {
  node_id: "node-target",
  workflow_id: "workflow-1",
  node_type: "image",
  creative_role: "product_main",
  role_contract_version: "ad-media-role-v1",
  title: "Product Main",
  status: "ready",
  summary_prompt: null,
  generation_prompt: null,
  structured_content: {},
  model_id: null,
  parameters: {},
  prompt_context_snapshot_id: null,
  output_asset_id: null,
  position: { x: 0, y: 0 },
  revision: 1,
  error: null,
  variation_draft: null,
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:00Z",
};

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 2,
  layout_revision: 1,
  nodes: [node],
  bindings: [{
    binding_id: "binding-reference",
    workflow_id: "workflow-1",
    target_node_id: "node-target",
    source: {
      kind: "image_asset",
      source_asset_id: "asset-1",
      source_asset_version_id: "version-2",
    },
    input_role: "image_reference",
    label: "Reference",
    required: true,
    enabled: true,
    order: 0,
    revision: 1,
  }],
  assets: [{
    asset_id: "asset-1",
    version_id: "version-1",
    media_type: "image",
    source_type: "upload",
    display_name: "Reference",
    mime_type: "image/png",
    status: "ready",
    preview_url: "/api/v2/assets/asset-1/preview",
    media_url: "/api/v2/assets/asset-1/content",
    width: 100,
    height: 100,
    duration_seconds: null,
    checksum: "checksum",
  }],
};

describe("NodeReferenceStrip", () => {
  it("previews the bound AssetVersion through the preview rendition", async () => {
    render(
      <NodeReferenceStrip
        workflow={workflow}
        node={node}
        pending={false}
        perform={async (action) => {
          await action();
          return true;
        }}
        deleteBinding={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await waitFor(() => expect(
      screen.getByRole("img", { name: "Reference reference" }).getAttribute("src"),
    ).toBe("/api/v2/assets/asset-1/preview?v=version-2"));
  });
});
