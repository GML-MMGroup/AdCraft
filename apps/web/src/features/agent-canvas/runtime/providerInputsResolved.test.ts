import { describe, expect, it } from "vitest";

import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";
import {
  durationHintForResolvedInputs,
  parseProviderInputsResolvedEvent,
  resolvedInputPurposeLabel,
} from "./providerInputsResolved.ts";

function event(payload: Record<string, unknown>): CanvasRuntimeEventV2 {
  return {
    seq: 21,
    workflow_id: "workflow-1",
    event_type: "provider_inputs_resolved",
    execution_id: "execution-1",
    node_id: "node-video-1",
    asset_id: null,
    binding_id: null,
    created_at: "2026-07-30T00:00:00Z",
    payload,
  };
}

describe("provider_inputs_resolved", () => {
  it("reads the redacted direct manifest in deterministic binding order", () => {
    const resolved = parseProviderInputsResolvedEvent(event({
      node_id: "node-video-1",
      model_id: "seedance-2",
      input_counts: { text: 0, script: 0, image: 2, video: 0, audio: 0 },
      inputs: [
        {
          binding_id: "binding-scene",
          asset_id: "asset-scene",
          media_type: "image",
          input_role: "visual_reference",
          source_semantic_role: "scene_design_board",
          reference_purpose: "scene_reference",
          required: true,
          display_order: 3,
          label: "Image 2",
          checksum: "scene-checksum",
          provider_input_value: "https://private.example/scene?token=secret",
        },
        {
          binding_id: "binding-storyboard",
          asset_id: "asset-storyboard",
          media_type: "image",
          input_role: "visual_reference",
          source_semantic_role: "storyboard_grid",
          reference_purpose: "storyboard_sequence",
          required: true,
          display_order: 2,
          label: "Image 1",
          checksum: "storyboard-checksum",
          data_url: "data:image/png;base64,secret",
        },
      ],
      requested_duration_seconds: 30,
      effective_duration_seconds: 15,
      normalizations: ["duration_clamped_to_provider_limit"],
      omitted_optional_inputs: [],
    }));

    expect(resolved?.inputs.map((input) => input.binding_id)).toEqual([
      "binding-storyboard",
      "binding-scene",
    ]);
    expect(resolvedInputPurposeLabel(resolved!.inputs[0]!)).toBe("Storyboard Grid");
    expect(resolvedInputPurposeLabel(resolved!.inputs[1]!)).toBe("Scene Design Board");
    expect(durationHintForResolvedInputs(resolved!)).toContain("15-second");
    expect(JSON.stringify(resolved)).not.toMatch(/private\\.example|data:image|secret/);
  });

  it("reads the backend audit envelope without retaining provider transport data", () => {
    const resolved = parseProviderInputsResolvedEvent(event({
      seedance_input_manifest: {
        schema_version: "seedance_input_manifest_audit_v1",
        node_id: "node-video-1",
        model_id: "seedance-2",
        prompt_hash: "prompt-hash",
        text_inputs: [{
          binding_id: "binding-script",
          source_node_id: "node-script-1",
          source_node_revision: 4,
          source_type: "script",
          input_role: "instruction",
          display_order: 0,
          content_hash: "script-hash",
          label: "Script 1",
        }],
        media_inputs: [{
          binding_id: "binding-storyboard",
          asset_id: "asset-storyboard",
          media_type: "image",
          input_role: "visual_reference",
          source_semantic_role: "storyboard_grid",
          reference_purpose: "storyboard_sequence",
          required: true,
          display_order: 1,
          provider_input_type: "image_url",
          checksum: "storyboard-checksum",
          label: "Image 1",
          byte_count: 2048,
          provider_input_value: "/tmp/private.png",
        }],
        input_counts: { text: 0, script: 1, image: 1, video: 0, audio: 0 },
        aspect_ratio: "16:9",
        resolution: "720p",
        requested_duration_seconds: 12,
        effective_duration_seconds: 12,
        generate_audio: true,
        normalizations: [],
      },
      optional_input_omissions: [{
        binding_id: "binding-audio",
        reason: "provider_reference_delivery_unavailable",
        provider_input_value: "https://private.example/audio",
      }],
    }));

    expect(resolved).toMatchObject({
      node_id: "node-video-1",
      model_id: "seedance-2",
      requested_duration_seconds: 12,
      effective_duration_seconds: 12,
      inputs: [
        {
          binding_id: "binding-script",
          label: "Script 1",
          source_node_id: "node-script-1",
        },
        {
          binding_id: "binding-storyboard",
          label: "Image 1",
          source_semantic_role: "storyboard_grid",
        },
      ],
      omitted_optional_inputs: [{
        binding_id: "binding-audio",
        reason: "provider_reference_delivery_unavailable",
      }],
    });
    expect(JSON.stringify(resolved)).not.toMatch(/\/tmp\/private|private\.example/);
  });

  it("ignores unrelated events and malformed input summaries", () => {
    expect(parseProviderInputsResolvedEvent({
      ...event({}),
      event_type: "provider_execution_started",
    })).toBeNull();
    expect(parseProviderInputsResolvedEvent(event({
      node_id: "node-video-1",
      inputs: [{ binding_id: "", label: "Image 1" }],
    }))?.inputs).toEqual([]);
  });
});
