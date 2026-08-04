import { describe, expect, it } from "vitest";

import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";
import { modelResolutionFromEvent } from "./modelResolution.ts";

function event(payload: Record<string, unknown>): CanvasRuntimeEventV2 {
  return {
    seq: 1,
    workflow_id: "workflow-1",
    event_type: "node_generation_started",
    project_id: "project-1",
    execution_id: "execution-1",
    node_id: "image-1",
    asset_id: null,
    binding_id: null,
    conversation_id: null,
    turn_id: null,
    action_id: null,
    trace_id: null,
    span_id: null,
    transition_key: null,
    attempt: 1,
    created_at: "2026-08-03T00:00:00Z",
    payload,
  };
}

describe("modelResolutionFromEvent", () => {
  it("keeps only the documented non-secret resolution metadata", () => {
    expect(modelResolutionFromEvent(event({
      model_resolution: {
        model_ref: "siliconflow:zai-org/GLM-5.2",
        provider_id: "siliconflow",
        provider_model_id: "zai-org/GLM-5.2",
        credential_revision: 3,
        catalog_revision: 12,
        api_key: "must-not-be-copied",
      },
    }))).toEqual({
      node_id: "image-1",
      model_ref: "siliconflow:zai-org/GLM-5.2",
      provider_id: "siliconflow",
      provider_model_id: "zai-org/GLM-5.2",
      credential_revision: 3,
      catalog_revision: 12,
    });
  });

  it("ignores incomplete payloads", () => {
    expect(modelResolutionFromEvent(event({ model_resolution: { model_ref: "missing-fields" } }))).toBeNull();
  });
});
