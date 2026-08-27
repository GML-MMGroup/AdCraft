import { describe, expect, it } from "vitest";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import {
  hasPromptReadyDraft,
  isNodePromptReady,
  promptPreparationForNode,
} from "./promptPreparation.ts";

function node(promptPreparation: CanvasNodeV2["prompt_preparation"]): CanvasNodeV2 {
  return {
    node_id: "node-1",
    workflow_id: "workflow-1",
    node_type: "image",
    creative_role: "product",
    role_contract_version: "ad-media-role-v2",
    title: "Product Main",
    status: "draft",
    summary_prompt: "A clean product hero image.",
    generation_prompt: promptPreparation?.status === "ready" ? "A detailed product hero prompt." : null,
    structured_content: {},
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    prompt_preparation: promptPreparation,
    variation_draft: null,
    created_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-20T00:00:00Z",
  };
}

describe("Agent Canvas prompt preparation authority", () => {
  it("does not treat a missing V2 prompt preparation projection as Ready", () => {
    const draft = node(null);

    expect(promptPreparationForNode(draft)).toBeNull();
    expect(isNodePromptReady(draft)).toBe(false);
  });

  it("allows Run only for the backend Ready projection", () => {
    const ready = node({
      status: "ready",
      operation_id: "operation-1",
      attempt_no: 1,
      context_snapshot_id: "snapshot-1",
      prompt_digest: "a".repeat(64),
      role_variant: "product_main",
      recipe_id: "product",
      recipe_version: "2",
      recipe_digest: "sha256:" + "b".repeat(64),
      requirement_revision_id: "requirement-1",
      requirement_revision_no: 1,
      document_revisions: {},
      binding_digest: null,
      style_projection_digest: null,
      brief_digest: null,
      parameter_origins: [],
      attempt_stage: "ready",
      error: null,
      updated_at: "2026-08-20T00:00:00Z",
    });

    expect(isNodePromptReady(ready)).toBe(true);
    expect(hasPromptReadyDraft([node(null), ready])).toBe(true);
    expect(isNodePromptReady({ ...ready, execution_mode: "source_only" })).toBe(false);
    expect(hasPromptReadyDraft([{ ...ready, execution_mode: "source_only" }])).toBe(false);
  });

  it("does not expose Global Run when no existing Draft has a prepared prompt", () => {
    expect(hasPromptReadyDraft([node(null)])).toBe(false);
  });
});
