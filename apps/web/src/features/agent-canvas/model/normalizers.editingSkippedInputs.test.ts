import { describe, expect, it } from "vitest";

import {
  normalizeEditingExportAcceptedV2,
  normalizeEditingNodeContentV2,
} from "./normalizers.ts";

const skippedBgm = {
  reference_id: "binding-bgm",
  node_id: "node-bgm",
  asset_id: null,
  reason: "omitted_no_output",
};

function completedComposition(reason = "omitted_no_output") {
  return {
    manifest: {
      video_entries: [{ binding_id: "binding-video" }],
      bgm: { binding_id: "binding-bgm" },
      output: {},
      manifest_revision: 1,
      timeline_duration_seconds: 30,
    },
    dirty: false,
    preview: {
      clips: [],
      bgm_binding_id: "binding-bgm",
      bgm_node_id: "node-bgm",
      bgm_asset_id: null,
      bgm_availability: "pending",
      estimated_duration_seconds: 30,
      warnings: ["binding-bgm:omitted_no_output"],
    },
    last_successful_export: {
      export_id: "export-1",
      status: "completed",
      manifest_revision: 1,
      fingerprint: "fingerprint-1",
      ready_video_node_ids: ["node-video"],
      skipped_inputs: [{ ...skippedBgm, reason }],
      bgm_node_id: null,
      output_asset_id: "asset-export",
      error: null,
      started_at: "2026-10-23T13:04:01Z",
      finished_at: "2026-10-23T13:04:12Z",
    },
    active_export: null,
  };
}

describe("Editing exports with skipped inputs", () => {
  it("keeps a completed composition readable when its BGM has no output", () => {
    const content = normalizeEditingNodeContentV2(completedComposition());

    expect(content.manifest.video_entries[0]?.binding_id).toBe("binding-video");
    expect(content.preview.bgm_availability).toBe("pending");
    expect(content.last_successful_export).toMatchObject({
      status: "completed",
      output_asset_id: "asset-export",
      bgm_node_id: null,
      skipped_inputs: [skippedBgm],
    });
  });

  it("accepts export responses that omitted an input with no output", () => {
    const accepted = normalizeEditingExportAcceptedV2({
      workflow_id: "workflow-1",
      node_id: "node-editing",
      export_id: "export-1",
      status: "completed",
      manifest_revision: 1,
      ready_video_node_ids: ["node-video"],
      skipped_inputs: [skippedBgm],
      bgm_node_id: null,
      events_cursor: 19,
    });

    expect(accepted.skipped_inputs).toEqual([skippedBgm]);
    expect(accepted.status).toBe("completed");
  });

  it("still rejects unknown skip reasons with the affected field path", () => {
    expect(() => normalizeEditingNodeContentV2(completedComposition("unknown_reason")))
      .toThrow("editing.last_successful_export.skipped_inputs[0].reason");
  });
});
