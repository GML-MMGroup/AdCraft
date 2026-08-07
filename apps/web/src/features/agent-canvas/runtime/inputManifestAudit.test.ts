import { describe, expect, it } from "vitest";

import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";
import {
  inputManifestAuditFromEvent,
  upstreamInputReadinessIssueFromDetails,
} from "./inputManifestAudit.ts";

function event(payload: Record<string, unknown>): CanvasRuntimeEventV2 {
  return {
    seq: 17,
    workflow_id: "workflow-1",
    event_type: "provider_inputs_resolved",
    project_id: "project-1",
    execution_id: "execution-1",
    node_id: "node-video-1",
    asset_id: null,
    binding_id: null,
    conversation_id: null,
    turn_id: null,
    action_id: null,
    trace_id: null,
    span_id: null,
    transition_key: "node-run:node-video-1:inputs-resolved:1",
    attempt: 1,
    created_at: "2026-07-31T04:00:00Z",
    payload,
  };
}

describe("inputManifestAuditFromEvent", () => {
  it("keeps only the sanitized ordered input audit returned by the backend", () => {
    const audit = inputManifestAuditFromEvent(event({
      input_manifest_id: "manifest-1",
      node_run_id: "node-run-1",
      text_inputs: [{
        binding_id: "binding-script",
        source_node_id: "node-script-1",
        snapshot_id: "snapshot-1",
        input_role: "text_context",
        required: true,
        display_order: 0,
        content: "must not survive into frontend state",
      }],
      world_setting_inputs: [{
        binding_id: "binding-world-setting",
        source_node_id: "node-world-setting",
        source_node_revision: 3,
        source_content_digest: "a".repeat(64),
        source_core_digest: "b".repeat(64),
        required: true,
        display_order: 1,
        target_audience: "video_director",
        compiler_id: "world-setting-context-compiler-v2",
        compiler_digest: "c".repeat(64),
        context_digest: "d".repeat(64),
        context: { private: "must not survive into frontend state" },
      }],
      media_inputs: [{
        binding_id: "binding-image",
        source_node_id: "node-image-1",
        asset_id: "asset-image-1",
        media_type: "image",
        input_role: "image_reference",
        source_semantic_role: "storyboard_grid",
        required: false,
        transport_type: "https_url",
        media_url: "https://must-not-be-retained.example/image.png",
        display_order: 2,
      }],
      omitted_optional_inputs: [{
        binding_id: "binding-optional",
        source_node_id: "node-optional-1",
        reason_code: "source_not_ready",
      }],
      normalizations: [{ kind: "provider_ordering" }],
    }));

    expect(audit).toEqual({
      node_id: "node-video-1",
      input_manifest_id: "manifest-1",
      execution_id: "execution-1",
      node_run_id: "node-run-1",
      text_inputs: [{
        binding_id: "binding-script",
        source_node_id: "node-script-1",
        snapshot_id: "snapshot-1",
        input_role: "text_context",
        required: true,
        display_order: 0,
      }],
      world_setting_inputs: [{
        binding_id: "binding-world-setting",
        source_node_id: "node-world-setting",
        source_node_revision: 3,
        source_content_digest: "a".repeat(64),
        source_core_digest: "b".repeat(64),
        required: true,
        display_order: 1,
        target_audience: "video_director",
        compiler_id: "world-setting-context-compiler-v2",
        compiler_digest: "c".repeat(64),
        context_digest: "d".repeat(64),
      }],
      media_inputs: [{
        binding_id: "binding-image",
        source_node_id: "node-image-1",
        asset_id: "asset-image-1",
        media_type: "image",
        input_role: "image_reference",
        source_semantic_role: "storyboard_grid",
        transport_type: "https_url",
        required: false,
        display_order: 2,
      }],
      omitted_optional_inputs: [{
        binding_id: "binding-optional",
        source_node_id: "node-optional-1",
        reason_code: "source_not_ready",
      }],
    });
  });

  it("does not derive an input audit or graph edge from unrelated events", () => {
    expect(inputManifestAuditFromEvent({
      ...event({ input_manifest_id: "manifest-1" }),
      event_type: "node_generation_started",
    })).toBeNull();
  });
});

describe("upstreamInputReadinessIssueFromDetails", () => {
  it("returns the backend-provided required source node identities only", () => {
    expect(upstreamInputReadinessIssueFromDetails("node-video-1", {
      missing_required_source_node_ids: ["node-script-1", "node-image-1"],
      source_node_id: "node-script-1",
      media_url: "https://must-not-be-retained.example/image.png",
    })).toEqual({
      target_node_id: "node-video-1",
      source_node_ids: ["node-script-1", "node-image-1"],
    });
  });
});
