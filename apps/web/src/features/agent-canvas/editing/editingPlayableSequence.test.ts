import { describe, expect, it } from "vitest";

import type { CanvasNodeV2, EditingVideoEntryV2, ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import type { EditingBoundInput } from "./editingModel.ts";
import { buildPlayableEditingSequence } from "./editingPlayableSequence.ts";

function video(
  referenceId: string,
  options: {
    enabled?: boolean;
    assetStatus?: ProjectAssetSummaryV2["status"];
    mediaUrl?: string | null;
    nodeStatus?: CanvasNodeV2["status"] | null;
    trimStart?: number;
    trimEnd?: number | null;
  } = {},
): EditingBoundInput<EditingVideoEntryV2> {
  const nodeStatus = options.nodeStatus === undefined ? null : options.nodeStatus;
  return {
    referenceId,
    binding: null,
    node: nodeStatus === null ? null : { status: nodeStatus } as CanvasNodeV2,
    asset: {
      asset_id: `asset-${referenceId}`,
      media_type: "video",
      status: options.assetStatus ?? "ready",
      media_url: options.mediaUrl === undefined ? `/media/${referenceId}` : options.mediaUrl,
      duration_seconds: 10,
    } as ProjectAssetSummaryV2,
    entry: {
      binding_id: referenceId,
      asset_id: null,
      enabled: options.enabled ?? true,
      trim_start_seconds: options.trimStart ?? 0,
      trim_end_seconds: options.trimEnd === undefined ? 10 : options.trimEnd,
      volume: 1,
      preserve_native_audio: true,
      transition: "cut",
      transition_duration_seconds: 0,
      fit_mode: "fit",
    },
  };
}

describe("buildPlayableEditingSequence", () => {
  it("treats null positions and duration as automatic, preserving fractional source durations", () => {
    const first = video("first", { trimEnd: null });
    const second = video("second", { trimEnd: null });
    first.entry.timeline_start_seconds = null;
    second.entry.timeline_start_seconds = null;
    first.asset!.duration_seconds = 15.041667;
    second.asset!.duration_seconds = 15.041667;
    const result = buildPlayableEditingSequence([first, second], null);
    expect(result.duration).toBeCloseTo(30.083334, 6);
    expect(result.segments.map(segment => segment.timelineStart)).toEqual([0, 15.041667]);
    expect(result.segments[1]?.timelineEnd).toBeCloseTo(30.083334, 6);
    expect(first.entry.timeline_start_seconds).toBeNull();
    expect(second.entry.timeline_start_seconds).toBeNull();
  });

  it("keeps playable clips ordered while the ruler retains the imported source duration", () => {
    const first = video("first", { trimStart: 1, trimEnd: 4 });
    const disabled = video("disabled", { enabled: false });
    const sourceDraft = video("source-draft", { nodeStatus: "draft" });
    const assetPending = video("asset-pending", { assetStatus: "pending" });
    const missingUrl = video("missing-url", { mediaUrl: null });
    const second = video("second", { nodeStatus: "ready", trimStart: 2, trimEnd: 6 });

    const sequence = buildPlayableEditingSequence([
      first,
      disabled,
      sourceDraft,
      assetPending,
      missingUrl,
      second,
    ]);

    expect(sequence.videos.map((input) => input.referenceId)).toEqual(["first", "second"]);
    expect(sequence.inactiveVideos.map((input) => input.referenceId)).toEqual([
      "disabled",
      "source-draft",
      "asset-pending",
      "missing-url",
    ]);
    expect(sequence.segments).toEqual([
      {
        referenceId: "first",
        timelineStart: 0,
        timelineEnd: 3,
        sourceStart: 1,
        sourceEnd: 4,
      },
      {
        referenceId: "second",
        timelineStart: 3,
        timelineEnd: 7,
        sourceStart: 2,
        sourceEnd: 6,
      },
    ]);
    expect(sequence.duration).toBe(60);
  });

  it("uses explicit timeline positions and preserves gaps", () => {
    const first = video("first", { trimStart: 1, trimEnd: 4 });
    const second = video("second", { trimStart: 2, trimEnd: 6 });
    first.entry.timeline_start_seconds = 0;
    second.entry.timeline_start_seconds = 12;

    const sequence = buildPlayableEditingSequence([first, second], 30);

    expect(sequence.videos.map((input) => input.referenceId)).toEqual(["first", "second"]);
    expect(sequence.segments.map(({ timelineStart, timelineEnd }) => [timelineStart, timelineEnd]))
      .toEqual([[0, 3], [12, 16]]);
    expect(sequence.duration).toBe(30);
  });
});
