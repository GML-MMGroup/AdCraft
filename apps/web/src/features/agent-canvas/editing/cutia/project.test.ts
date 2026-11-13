import { describe, expect, it } from "vitest";
import { editingFixture } from "./fixtures.test-support.ts";
import { CUTIA_PROJECT_KEY, initialCutiaSnapshot, isCutiaSnapshot, legacyMigrationNotes, snapshotKey } from "./project.ts";

describe("Cutia project migration", () => {
  it("preserves source trims and BGM volume while translating to native Cutia durations", () => {
    const { snapshot } = editingFixture();
    expect(snapshot.project.scenes[0].tracks[0].elements[0]).toMatchObject({ mediaId: "video-1", startTime: 0, duration: 3, trimStart: 2, trimEnd: 1 });
    const bgm = snapshot.project.scenes[0].tracks.find((track) => track.id === "bgm")!;
    expect(bgm.elements[0]).toMatchObject({ startTime: 0, duration: 2, volume: 0.35 });
    expect(bgm.elements[1]).toMatchObject({ startTime: 2, duration: 2, volume: 0.35 });
    expect(snapshot.project.settings).toMatchObject({ fps: 10, canvasSize: { width: 320, height: 180 } });
    expect(isCutiaSnapshot(snapshot)).toBe(true);
  });

  it("preserves fill, source audio volume and an explicit empty tail", () => {
    const { workflow, node } = editingFixture();
    const manifest = node.structured_content.manifest as Record<string, unknown>;
    manifest.bgm = null;
    manifest.timeline_duration_seconds = 8;
    manifest.output = { resolution: "180x320", fps: 24 };
    manifest.video_entries = [{ asset_id: "video-1", trim_start_seconds: 2, trim_end_seconds: 5, volume: 0.4, fit_mode: "fill" }];
    const migrated = initialCutiaSnapshot(workflow, node);
    const tracks = migrated.project.scenes[0].tracks;
    expect(tracks[0].elements[0]).toMatchObject({ muted: true, transform: { scale: 256 / 81 } });
    expect(tracks.find(track => track.id === "native-audio")?.elements[0]).toMatchObject({ duration: 3, trimStart: 2, volume: 0.4 });
    expect(tracks.find(track => track.id === "timeline-duration")?.elements[0]).toMatchObject({ startTime: 3, duration: 5 });
  });

  it("ignores retired legacy fades without migration warnings", () => {
    const { workflow, node, snapshot } = editingFixture();
    const manifest = node.structured_content.manifest as { bgm: Record<string, unknown>; video_entries: Record<string, unknown>[] };
    manifest.bgm.fade_in_seconds = 1;
    manifest.bgm.fade_out_seconds = 1;
    manifest.video_entries[0].transition = "fade";
    manifest.video_entries[0].transition_duration_seconds = 0.5;
    expect(initialCutiaSnapshot(workflow, node)).toEqual(snapshot);
    expect(legacyMigrationNotes(workflow, node)).toEqual([]);
  });

  it("restores native multi-track edits instead of regenerating the legacy timeline", () => {
    const { node, workflow, snapshot } = editingFixture();
    snapshot.project.scenes[0].tracks.push({ id: "titles", type: "text", name: "Titles", hidden: false, elements: [] });
    node.parameters[CUTIA_PROJECT_KEY] = { snapshot };
    const restored = initialCutiaSnapshot(workflow, node);
    expect(restored.project.scenes[0].tracks.at(-1)?.id).toBe("titles");
    expect(restored.media.map((asset) => asset.assetId)).toEqual(["video-1", "bgm-1"]);
  });

  it("does not overwrite an unreadable saved project with an automatic migration", () => {
    const { node, workflow } = editingFixture();
    node.parameters[CUTIA_PROJECT_KEY] = { snapshot: { schemaVersion: 99 } };
    expect(() => initialCutiaSnapshot(workflow, node)).toThrow("saved editing project");
  });

  it("invalidates exports for content changes, but not timestamps or viewport changes", () => {
    const { snapshot } = editingFixture();
    const original = snapshotKey(snapshot);
    snapshot.project.metadata.updatedAt = new Date();
    snapshot.project.timelineViewState = { zoomLevel: 3, scrollLeft: 50, playheadTime: 1 };
    expect(snapshotKey(snapshot)).toBe(original);
    snapshot.project.scenes[0].tracks[0].elements[0].trimStart += 1;
    expect(snapshotKey(snapshot)).not.toBe(original);
  });
});
