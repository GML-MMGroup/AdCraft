import { describe, expect, it } from "vitest";
import { normalizeEditingNodeContentV2 } from "./normalizers.ts";

function content(start?: unknown, duration?: unknown, bgmAvailability?: unknown) {
  return {
    manifest: {
      video_entries: ["video-1", "video-2"].map(asset_id => ({
        asset_id, binding_id: null, enabled: true,
        ...(start === undefined ? {} : { timeline_start_seconds: start }),
        trim_start_seconds: 0, trim_end_seconds: null, volume: 1, preserve_native_audio: true,
        transition: "cut", transition_duration_seconds: 0, fit_mode: "fit",
      })),
      bgm: { asset_id: "bgm-1", binding_id: null, enabled: true, trim_start_seconds: 0,
        trim_end_seconds: null, volume: 0.2, fade_in_seconds: 0, fade_out_seconds: 0 },
      output: { resolution: null, aspect_ratio: null, fps: null, video_codec: "h264", audio_codec: "aac", container: "mp4" },
      manifest_revision: 1,
      ...(duration === undefined ? {} : { timeline_duration_seconds: duration }),
    },
    dirty: true,
    preview: {
      clips: [], bgm_binding_id: null, bgm_node_id: null, bgm_asset_id: null,
      ...(bgmAvailability === undefined ? {} : { bgm_availability: bgmAvailability }),
      estimated_duration_seconds: 30.083334, warnings: [],
    },
    last_successful_export: null, active_export: null,
  };
}

describe("Editing nullable wire fields", () => {
  it("continues to accept omitted legacy fields", () => {
    const result = normalizeEditingNodeContentV2(content());
    expect(result.manifest.video_entries[0]).not.toHaveProperty("timeline_start_seconds");
    expect(result.manifest).not.toHaveProperty("timeline_duration_seconds");
    expect(result.preview.bgm_availability).toBeNull();
  });

  it.each([
    [null, undefined, undefined], [undefined, null, undefined], [undefined, undefined, null], [null, null, null],
  ])("accepts explicit null independently and together: %j / %j / %j", (start, duration, bgm) => {
    const result = normalizeEditingNodeContentV2(content(start, duration, bgm));
    expect(result.manifest.video_entries[0]?.timeline_start_seconds).toBe(start);
    expect(result.manifest.timeline_duration_seconds).toBe(duration);
    expect(result.preview.bgm_availability).toBeNull();
    expect(result.manifest.video_entries).toHaveLength(2);
    expect(result.manifest.bgm?.asset_id).toBe("bgm-1");
    expect(result.preview.estimated_duration_seconds).toBe(30.083334);
  });

  it.each(["pending", "available", "failed"])("preserves concrete times and BGM %s", bgm => {
    const result = normalizeEditingNodeContentV2(content(0, 30.083334, bgm));
    expect(result.manifest.video_entries[0]?.timeline_start_seconds).toBe(0);
    expect(result.manifest.timeline_duration_seconds).toBe(30.083334);
    expect(result.preview.bgm_availability).toBe(bgm);
  });

  it.each([-1, "0", false, {}, NaN, Infinity])("still rejects invalid start %j", start => {
    expect(() => normalizeEditingNodeContentV2(content(start))).toThrow("timeline_start_seconds");
  });
  it.each([0, -1, "30", false, {}, NaN, Infinity])("still rejects invalid duration %j", duration => {
    expect(() => normalizeEditingNodeContentV2(content(undefined, duration))).toThrow("timeline_duration_seconds");
  });
  it.each(["ready", "", 0, false, {}])("still rejects invalid BGM availability %j", bgm => {
    expect(() => normalizeEditingNodeContentV2(content(undefined, undefined, bgm))).toThrow("bgm_availability");
  });
  it("does not relax unknown-field checking", () => {
    const input = content(null, null, null);
    expect(() => normalizeEditingNodeContentV2({ ...input, unexpected: true })).toThrow("unknown field");
  });
});
