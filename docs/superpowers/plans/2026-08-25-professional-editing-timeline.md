# Professional Editing Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the form-oriented Editing timeline with a professional zoomable timeline that shows real frames and audio waveform, supports direct trim handles, silently persists on release, and previews complete landscape, portrait, and square video.

**Architecture:** Keep `AgentCanvasEditingPanel` as the shell and backend authority boundary. Extract pure timeline math, a serialized manifest mutation queue, media sampling hooks, direct-manipulation clip components, an audio lane, and a complete preview stage into focused modules. The browser derives thumbnails, waveform, and draft playback only; final rendering remains backend-owned.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, Pointer Events, HTMLVideoElement, Canvas 2D, Web Audio API, existing Agent Canvas Node PATCH and Editing Export APIs.

**Spec:** `docs/superpowers/specs/2026-08-25-professional-editing-timeline-design.md`

## Global Constraints

- Do not change backend schemas or endpoints.
- Do not add FFmpeg, WebGL, or a browser-side final render pipeline.
- Preserve Export, cancel, Download, Add to Canvas, output settings, omitted inputs, warnings, and conflict behavior.
- Pointer movement is local-only; one silent mutation is committed on pointer release.
- Serialize commits per Editing node and coalesce only not-yet-started writes.
- Keep the editor black, white, and gray; do not add gradients or decorative glow.
- Use actual sampled video frames and decoded audio peaks when available, with non-blocking canonical preview fallbacks.
- Final Export remains authoritative; draft timeline playback is an editorial preview.
- Run focused tests during implementation, then run typecheck, lint, and build once.

---

## File Structure

**Create**

- `apps/web/src/features/agent-canvas/editing/editingTimelineMath.ts`: pure time, zoom, segment, and trim calculations.
- `apps/web/src/features/agent-canvas/editing/editingTimelineMath.test.ts`: deterministic timeline math coverage.
- `apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.ts`: bounded frame sampling and cache access.
- `apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx`: sampling, caching, and fallback tests.
- `apps/web/src/features/agent-canvas/editing/useAudioWaveform.ts`: audio decode and peak reduction cache.
- `apps/web/src/features/agent-canvas/editing/useAudioWaveform.test.tsx`: peak reduction and failure fallback tests.
- `apps/web/src/features/agent-canvas/editing/EditingTimelineViewport.tsx`: shared zoom, scroll, ruler, and playhead coordinate surface.
- `apps/web/src/features/agent-canvas/editing/VideoTimelineClip.tsx`: frame strip, selection, and trim handle interaction.
- `apps/web/src/features/agent-canvas/editing/AudioWaveformTrack.tsx`: waveform lane and compact audio controls.
- `apps/web/src/features/agent-canvas/editing/EditingPreviewStage.tsx`: complete output frame and draft timeline playback.
- `apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx`: direct trim, zoom, and retained-control component coverage.
- `apps/web/src/features/agent-canvas/editing/EditingPreviewStage.test.tsx`: preview ratio and playback mapping coverage.

**Modify**

- `apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.ts`: staged manifest updates and serialized commit queue.
- `apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx`: no-save-during-drag, release commit, coalescing, and rollback tests.
- `apps/web/src/features/agent-canvas/editing/EditingTimeline.tsx`: compose extracted viewport, clip, waveform, and properties components.
- `apps/web/src/features/agent-canvas/editing/AgentCanvasEditingPanel.tsx`: mount preview stage and pass staged/commit handlers.
- `apps/web/src/features/agent-canvas/editing/AgentCanvasEditingPanel.test.tsx`: update legacy assertions and protect existing actions.
- `apps/web/src/features/agent-canvas/editing/agent-canvas-editing.css`: professional timeline layout and complete preview sizing.

---

### Task 1: Shared Timeline and Trim Mathematics

**Files:**
- Create: `apps/web/src/features/agent-canvas/editing/editingTimelineMath.ts`
- Create: `apps/web/src/features/agent-canvas/editing/editingTimelineMath.test.ts`

**Interfaces:**
- Produces: `clampTrimRange()`, `editedClipDuration()`, `buildTimelineSegments()`, `fitPixelsPerSecond()`, `clampPixelsPerSecond()`, `timeToPixels()`, `pixelsToTime()`, `mapTimelineTimeToSource()`.
- Consumes: numeric source duration and the existing `EditingVideoEntryV2` trim fields.

- [ ] **Step 1: Write failing timeline math tests**

```ts
it("clamps trim handles without crossing the minimum duration", () => {
  expect(clampTrimRange({ sourceDuration: 10, start: 9.8, end: 4, edge: "start" }))
    .toEqual({ start: 3.5, end: 4 });
});

it("maps the sequence playhead into the trimmed source", () => {
  const segments = buildTimelineSegments([
    { referenceId: "a", sourceDuration: 8, trimStart: 2, trimEnd: 6 },
    { referenceId: "b", sourceDuration: 5, trimStart: 1, trimEnd: 4 },
  ]);
  expect(mapTimelineTimeToSource(segments, 5)).toMatchObject({
    referenceId: "b",
    sourceSeconds: 2,
  });
});

it("uses fit-all as the minimum zoom", () => {
  expect(fitPixelsPerSecond(900, 30)).toBe(30);
  expect(clampPixelsPerSecond(10, { viewportWidth: 900, duration: 30, max: 180 })).toBe(30);
});
```

- [ ] **Step 2: Run the test and verify missing exports fail**

Run: `npm test -- --run src/features/agent-canvas/editing/editingTimelineMath.test.ts`

Expected: FAIL because `editingTimelineMath.ts` does not exist.

- [ ] **Step 3: Implement typed pure helpers**

```ts
export const MIN_EDITED_CLIP_SECONDS = 0.5;

export interface TimelineSegment {
  referenceId: string;
  timelineStart: number;
  timelineEnd: number;
  sourceStart: number;
  sourceEnd: number;
}

export function timeToPixels(seconds: number, pixelsPerSecond: number): number {
  return seconds * pixelsPerSecond;
}

export function pixelsToTime(pixels: number, pixelsPerSecond: number): number {
  return pixelsPerSecond > 0 ? pixels / pixelsPerSecond : 0;
}
```

Implement clamping so the dragged edge moves while the opposite edge remains fixed, and implement sequence mapping with half-open intervals except for the terminal boundary.

- [ ] **Step 4: Run the focused test**

Run: `npm test -- --run src/features/agent-canvas/editing/editingTimelineMath.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/editingTimelineMath.ts apps/web/src/features/agent-canvas/editing/editingTimelineMath.test.ts
git commit -m "feat(editing): add shared timeline math"
```

---

### Task 2: Staged Editing Manifest and Serialized Silent Commits

**Files:**
- Modify: `apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.ts`
- Modify: `apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx`

**Interfaces:**
- Consumes: `updateEditingVideoEntry()` and existing `patchNode()`.
- Produces: `stageVideoUpdate(referenceId, patch)`, `commitStagedManifest()`, `discardStagedManifest()`, `hasPendingManifestCommit`.

- [ ] **Step 1: Add failing hook tests for drag staging and persistence**

```tsx
act(() => result.current.stageVideoUpdate("binding-video", {
  trim_start_seconds: 1.25,
}));
expect(result.current.inputs.videos[0].entry.trim_start_seconds).toBe(1.25);
expect(patchNode).not.toHaveBeenCalled();

await act(async () => result.current.commitStagedManifest());
expect(patchNode).toHaveBeenCalledTimes(1);
```

Add a deferred-promise test that commits values `1`, `2`, and `3` while the first write is in flight and verifies the server sees `1` followed by `3`, never `2`. Add a rejection test that restores the last confirmed manifest only when no newer staged value exists.

- [ ] **Step 2: Run the hook test and verify it fails**

Run: `npm test -- --run src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx`

Expected: FAIL because staged update APIs do not exist.

- [ ] **Step 3: Refactor save state into staged and queued refs**

```ts
const stagedManifestRef = useRef<EditingManifestV2 | null>(null);
const queuedCommitRef = useRef<EditingManifestV2 | null>(null);
const commitLoopRef = useRef<Promise<void> | null>(null);

const stageVideoUpdate = useCallback((referenceId, patch) => {
  const next = updateEditingVideoEntry(currentManifest(), referenceId, patch);
  stagedManifestRef.current = next;
  setDraftManifest({ nodeId: node.node_id, manifest: next });
}, [currentManifest, node.node_id]);
```

Implement one commit loop per hook instance. The loop takes the newest queued manifest, awaits `patchNode(..., { coalesce: true })`, then checks whether another final state arrived. An older completion must not clear a newer draft.

- [ ] **Step 4: Preserve immediate property updates**

Keep `updateVideo`, `setBgm`, `setBgmVolume`, and `setOutput` as explicit immediate actions, but route them through the same serialized queue so ETag-sensitive writes cannot overlap.

- [ ] **Step 5: Run hook and editing model tests**

Run: `npm test -- --run src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx src/features/agent-canvas/editing/editingModel.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.ts apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx
git commit -m "feat(editing): stage and serialize timeline updates"
```

---

### Task 3: Bounded Real Video Frame Sampling

**Files:**
- Create: `apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.ts`
- Create: `apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx`

**Interfaces:**
- Consumes: `assetId`, `mediaUrl`, `previewUrl`, source trim range, rendered width, and visibility.
- Produces: `VideoFrameSample[]` where each item is `{ sourceSeconds: number; url: string; sampled: boolean }`.

- [ ] **Step 1: Write failing tests for requested times, cache reuse, and fallback**

```ts
expect(frameSampleTimes({ start: 2, end: 8, renderedWidth: 480, targetFrameWidth: 80 }))
  .toEqual([2.5, 3.5, 4.5, 5.5, 6.5, 7.5]);

expect(frameCacheKey("asset-1", 2.504, 80, 45)).toBe("asset-1:2.50:80x45");
```

Render the hook with an injected sampler that rejects and verify every requested cell resolves to the canonical `previewUrl` without throwing.

- [ ] **Step 2: Run the test and verify it fails**

Run: `npm test -- --run src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx`

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement the sampler and module-level LRU cache**

```ts
export interface VideoFrameSample {
  sourceSeconds: number;
  url: string;
  sampled: boolean;
}

export interface VideoFrameRequest {
  assetId: string;
  mediaUrl: string | null;
  previewUrl: string | null;
  sourceStart: number;
  sourceEnd: number;
  renderedWidth: number;
  active: boolean;
}
```

Use one hidden video element per active request, seek serially, draw to a small Canvas, and store blob URLs in a bounded cache. Revoke evicted blob URLs. Stop scheduling when `document.hidden` is true. Do not block rendering while metadata is loading.

- [ ] **Step 4: Run the focused test**

Run: `npm test -- --run src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.ts apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx
git commit -m "feat(editing): sample timeline video frames"
```

---

### Task 4: Audio Peak Extraction and Waveform Track

**Files:**
- Create: `apps/web/src/features/agent-canvas/editing/useAudioWaveform.ts`
- Create: `apps/web/src/features/agent-canvas/editing/useAudioWaveform.test.tsx`
- Create: `apps/web/src/features/agent-canvas/editing/AudioWaveformTrack.tsx`

**Interfaces:**
- Consumes: canonical BGM asset URL, trim range, volume, enabled state, timeline scale, and existing BGM update callbacks.
- Produces: normalized peak buckets and an accessible waveform lane.

- [ ] **Step 1: Write failing peak reduction tests**

```ts
expect(reduceAudioPeaks(new Float32Array([0, -1, 0.5, 0.25]), 2))
  .toEqual([1, 0.5]);
expect(normalizePeakCount([], 4)).toEqual([0, 0, 0, 0]);
```

Add a hook test where `decodeAudioData` rejects and verify `status === "fallback"` with a stable peak array.

- [ ] **Step 2: Run the test and verify it fails**

Run: `npm test -- --run src/features/agent-canvas/editing/useAudioWaveform.test.tsx`

Expected: FAIL because waveform helpers do not exist.

- [ ] **Step 3: Implement decoded peak caching and fallback**

```ts
export type AudioWaveformState =
  | { status: "loading"; peaks: number[] }
  | { status: "ready"; peaks: number[] }
  | { status: "fallback"; peaks: number[] };
```

Fetch the asset once per URL, decode with `AudioContext`, combine channel magnitudes, and cache normalized base peaks. Resample base peaks to the rendered lane width without decoding again.

- [ ] **Step 4: Build `AudioWaveformTrack`**

Render a mirrored Canvas or SVG-free CSS bar waveform with a neutral gray unplayed region and brighter played region. Keep BGM name, mute, volume, fade, enabled, and trim properties available without nesting another card.

- [ ] **Step 5: Run the focused test**

Run: `npm test -- --run src/features/agent-canvas/editing/useAudioWaveform.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/useAudioWaveform.ts apps/web/src/features/agent-canvas/editing/useAudioWaveform.test.tsx apps/web/src/features/agent-canvas/editing/AudioWaveformTrack.tsx
git commit -m "feat(editing): add decoded audio waveform"
```

---

### Task 5: Zoomable Timeline and Direct Trim Handles

**Files:**
- Create: `apps/web/src/features/agent-canvas/editing/EditingTimelineViewport.tsx`
- Create: `apps/web/src/features/agent-canvas/editing/VideoTimelineClip.tsx`
- Create: `apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/editing/EditingTimeline.tsx`

**Interfaces:**
- Consumes: Task 1 math, Task 2 staged update APIs, Task 3 frame samples, and Task 4 waveform track.
- Produces: `onStageVideo(referenceId, patch)` during drag and `onCommitStagedManifest()` once on pointer release.

- [ ] **Step 1: Write failing direct-manipulation tests**

Mock `getBoundingClientRect()` and pointer capture. Verify:

```tsx
fireEvent.pointerDown(screen.getByRole("slider", { name: "Trim start Shot 1" }), {
  pointerId: 1,
  clientX: 100,
});
fireEvent.pointerMove(window, { pointerId: 1, clientX: 140 });
expect(onStageVideo).toHaveBeenCalled();
expect(onCommitStagedManifest).not.toHaveBeenCalled();
fireEvent.pointerUp(window, { pointerId: 1, clientX: 140 });
expect(onCommitStagedManifest).toHaveBeenCalledTimes(1);
```

Also verify the old `Trim start`, `Trim end`, and `Selected clip` numeric form labels are absent, while Transition, Fit, source audio, volume, and ordering controls remain.

- [ ] **Step 2: Run the timeline test and verify it fails**

Run: `npm test -- --run src/features/agent-canvas/editing/EditingTimeline.test.tsx`

Expected: FAIL because direct trim components do not exist.

- [ ] **Step 3: Build `EditingTimelineViewport`**

Implement a stable viewport with ruler, shared content width, playhead, horizontal scroll, fit-all, minus, slider, plus, double-click ruler reset, ordinary wheel scroll, and `Ctrl/Command + wheel` anchored zoom.

Expose:

```ts
interface EditingTimelineViewportRenderState {
  pixelsPerSecond: number;
  visibleStartSeconds: number;
  visibleEndSeconds: number;
  contentWidth: number;
}
```

- [ ] **Step 4: Build `VideoTimelineClip` and trim handles**

Use Pointer Events and window-level move/up listeners after capture. Show the handles only for the selected clip. Give each visible bar a minimum 18px hit area, slider semantics, arrow-key `0.1s` changes, and Shift+Arrow `1s` changes.

- [ ] **Step 5: Refactor `EditingTimeline` composition**

Replace the current absolute percentage lane and inspector with:

```tsx
<EditingTimelineViewport>
  <VideoTrack>
    {segments.map((segment) => <VideoTimelineClip key={segment.referenceId} />)}
  </VideoTrack>
  <AudioWaveformTrack />
</EditingTimelineViewport>
<ClipPropertiesToolbar />
```

Retain seek, selection, clip order, enabled, source audio, volume, transition, fit, BGM controls, and empty states.

- [ ] **Step 6: Run timeline, hook, and panel tests**

Run: `npm test -- --run src/features/agent-canvas/editing/EditingTimeline.test.tsx src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx src/features/agent-canvas/editing/AgentCanvasEditingPanel.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/EditingTimelineViewport.tsx apps/web/src/features/agent-canvas/editing/VideoTimelineClip.tsx apps/web/src/features/agent-canvas/editing/EditingTimeline.tsx apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx apps/web/src/features/agent-canvas/editing/AgentCanvasEditingPanel.test.tsx
git commit -m "feat(editing): add zoomable direct trim timeline"
```

---

### Task 6: Complete Preview Stage and Draft Playback Mapping

**Files:**
- Create: `apps/web/src/features/agent-canvas/editing/EditingPreviewStage.tsx`
- Create: `apps/web/src/features/agent-canvas/editing/EditingPreviewStage.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/editing/AgentCanvasEditingPanel.tsx`

**Interfaces:**
- Consumes: Task 1 timeline segment mapping, editing inputs, output aspect ratio/resolution, playhead, transport state, exported asset, and BGM settings.
- Produces: `onPlayheadChange`, `onPlayingChange`, and complete output-frame rendering.

- [ ] **Step 1: Write failing preview tests**

```tsx
render(<EditingPreviewStage outputAspectRatio="9:16" {...props} />);
expect(screen.getByTestId("editing-preview-frame").getAttribute("style"))
  .toContain("aspect-ratio: 9 / 16");
expect(screen.getByTestId("editing-preview-video").className)
  .toContain("agent-editing-preview__video--contain");
```

Add a two-clip mapping test that moves the playhead across the first segment boundary and verifies the active media URL and source current time switch to the second trimmed clip.

- [ ] **Step 2: Run the preview test and verify it fails**

Run: `npm test -- --run src/features/agent-canvas/editing/EditingPreviewStage.test.tsx`

Expected: FAIL because `EditingPreviewStage` does not exist.

- [ ] **Step 3: Build the complete output-frame stage**

Derive ratio in this order:

1. `manifest.output.aspect_ratio`;
2. parsed output resolution;
3. exported asset width/height;
4. active source asset width/height;
5. `16 / 9` fallback.

Place that ratio frame inside a flexible black stage with `max-width: 100%`, `max-height: 100%`, and media `object-fit: contain`.

- [ ] **Step 4: Implement draft sequence playback**

Use `mapTimelineTimeToSource()` to seek the active source video. Keep a separate BGM audio element synchronized within a small tolerance. Stop playback at timeline end. Exported output remains available as the authoritative output view without replacing the draft timeline state.

- [ ] **Step 5: Mount the stage in `AgentCanvasEditingPanel`**

Move preview-specific refs and transport synchronization out of the panel. Pass timeline inputs, manifest, exported asset, playhead, muted, and playing values through a typed props interface.

- [ ] **Step 6: Run preview and panel tests**

Run: `npm test -- --run src/features/agent-canvas/editing/EditingPreviewStage.test.tsx src/features/agent-canvas/editing/AgentCanvasEditingPanel.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/EditingPreviewStage.tsx apps/web/src/features/agent-canvas/editing/EditingPreviewStage.test.tsx apps/web/src/features/agent-canvas/editing/AgentCanvasEditingPanel.tsx
git commit -m "feat(editing): add complete timeline preview stage"
```

---

### Task 7: Professional Visual Integration and Final Verification

**Files:**
- Modify: `apps/web/src/features/agent-canvas/editing/agent-canvas-editing.css`
- Modify: `apps/web/src/features/agent-canvas/editing/AgentCanvasEditingPanel.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx`

**Interfaces:**
- Consumes: all components from Tasks 1-6.
- Produces: final black/white/gray editor presentation and verified retained behavior.

- [ ] **Step 1: Add final retained-behavior assertions**

Verify that a readable export still exposes Download and Add to Canvas, Export remains disabled with no ready video, export-running state disables authoring but not zoom/playback, and output resolution/aspect/FPS controls still update through the serialized mutation queue.

- [ ] **Step 2: Apply the professional editor CSS**

Implement:

- a complete preview frame centered in a black stage;
- a taller video lane with frame strips;
- a compact mirrored waveform lane;
- narrow visible trim bars with generous hit areas;
- a white playhead and neutral selected state;
- stable track headers and shared row geometry;
- horizontal timeline overflow without vertical clipping;
- compact icon-based zoom and transport controls;
- no gradients or colored decorative effects.

- [ ] **Step 3: Run all focused Editing tests**

Run:

```bash
npm test -- --run \
  src/features/agent-canvas/editing/editingModel.test.ts \
  src/features/agent-canvas/editing/editingTimelineMath.test.ts \
  src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx \
  src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx \
  src/features/agent-canvas/editing/useAudioWaveform.test.tsx \
  src/features/agent-canvas/editing/EditingTimeline.test.tsx \
  src/features/agent-canvas/editing/EditingPreviewStage.test.tsx \
  src/features/agent-canvas/editing/AgentCanvasEditingPanel.test.tsx
```

Expected: all focused Editing tests PASS.

- [ ] **Step 4: Run frontend static verification once**

Run:

```bash
npm run typecheck
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 5: Start the frontend and perform visual verification**

Run: `npm run dev -- --port 5190`

Use Playwright Chromium to verify at a desktop viewport:

- landscape, portrait, and square output frames remain complete;
- selected trim handles remain inside the clip and are easy to grab;
- zooming keeps ruler, frames, waveform, and playhead aligned;
- timeline scroll does not crop handles or waveform;
- frame sampling does not blank existing canonical preview images;
- Export, Download, Add to Canvas, close, transport, output settings, warnings, and omitted inputs remain reachable.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/agent-canvas-editing.css apps/web/src/features/agent-canvas/editing/AgentCanvasEditingPanel.test.tsx apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx
git commit -m "style(editing): finish professional timeline editor"
```

---

## Final Acceptance

- The preview never crops the complete output frame.
- Clips show actual sampled video frames or a canonical preview fallback.
- Audio shows decoded peaks or a stable fallback waveform.
- Trim handles update locally during drag and silently save once on release.
- Rapid releases cannot let stale writes overwrite the newest trim.
- Fit-all and zoomed horizontal navigation both work.
- Existing Editing authoring and Export features remain available.
- Focused tests, typecheck, lint, and build pass.
