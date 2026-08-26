# Editing Single-Track Free Position Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Change the Agent Canvas Editing timeline from derived contiguous ordering to a single fixed-duration track where clips support ordinary trim and free horizontal placement without overlap.

**Architecture:** Keep the canonical editing manifest as the source of truth. Add an optional per-video timeline start field to the frontend contract and derive each clip's rendered interval from its persisted start plus its trimmed source duration. Keep the timeline duration separate from clip extents, and use staged manifest updates for drag previews so a drag commits once on pointer release. The canonical backend must accept and persist the new timeline position field before this behavior can survive refresh or affect export; the frontend will not store a shadow-only position or synthesize a different payload.

**Tech Stack:** React, TypeScript, React Testing Library, Vitest, existing Editing Manifest patch queue, CSS transforms and pointer events.

## Global Constraints

- Keep exactly one video track; do not add multi-track UI or vertical track movement.
- Ordinary Trim only: no Ripple, Roll, Slip, Slide, automatic neighbor movement, or automatic re-anchoring to `0s`.
- The logical timeline duration is the initial imported total duration and must not change when clips are trimmed or moved.
- Same-track clips must not overlap; gaps are valid and preserved.
- Every user drag is previewed locally and committed once on pointer release; Escape and pointer cancellation discard the staged change.
- Existing BGM, audio controls, preview, export, ETag conflict handling, and manifest commit coordination remain intact.
- Do not modify `/data/wenwu.meng/adWorkflow` or `apps/api`; do not hide the backend contract gap with local-only persistence.

---

### Task 1: Establish the explicit timeline contract and math

**Files:**
- Modify: `apps/web/src/types-v2.ts:2909-2942`
- Modify: `apps/web/src/features/agent-canvas/model/normalizers.ts` at the Editing Manifest normalizer
- Modify: `apps/web/src/features/agent-canvas/editing/editingTimelineMath.ts`
- Modify: `apps/web/src/features/agent-canvas/editing/editingPlayableSequence.ts`
- Test: `apps/web/src/features/agent-canvas/editing/editingTimelineMath.test.ts`
- Test: `apps/web/src/features/agent-canvas/editing/editingPlayableSequence.test.ts`

**Interfaces:**
- Add `timeline_start_seconds?: number` to `EditingVideoEntryV2` as an optional compatibility field until the backend begins returning it. The frontend must preserve it when present and include it in editing manifest patches for the backend contract update.
- Add `timeline_duration_seconds?: number` to `EditingManifestV2` as an optional persisted fixed-range field. When absent, initialize the view from the current source total and keep the value in the local manifest update only when the backend contract supports it.
- Change `TimelineClipInput` to accept `timelineStart?: number` and change `buildTimelineSegments(clips, timelineDuration?)` to return explicit-position segments, sorted by timeline position for playback and rendering while retaining the manifest reference IDs.
- Expose `clipTimelineStart`, `clipTimelineEnd`, `hasTimelineOverlap`, and `clampTimelineStart` helpers with frame-safe three-decimal seconds.

- [ ] **Step 1: Write failing math tests**

```ts
it("keeps a trimmed clip at its persisted timeline position", () => {
  const [segment] = buildTimelineSegments([
    { referenceId: "a", sourceDuration: 10, trimStart: 2, trimEnd: 8, timelineStart: 5 },
  ], 30);
  expect(segment).toMatchObject({ timelineStart: 5, timelineEnd: 11, sourceStart: 2, sourceEnd: 8 });
});

it("keeps gaps and fixed duration when clips are not contiguous", () => {
  const sequence = buildTimelineSegments([
    { referenceId: "a", sourceDuration: 10, trimStart: 0, trimEnd: 4, timelineStart: 0 },
    { referenceId: "b", sourceDuration: 10, trimStart: 1, trimEnd: 5, timelineStart: 8 },
  ], 30);
  expect(sequence.map(({ timelineStart, timelineEnd }) => [timelineStart, timelineEnd])).toEqual([[0, 4], [8, 12]]);
});

it("clamps a moved clip so its complete duration stays inside the fixed timeline", () => {
  expect(clampTimelineStart(28, 4, 30)).toBe(26);
  expect(clampTimelineStart(-2, 4, 30)).toBe(0);
});

it("detects overlap without changing either clip", () => {
  expect(hasTimelineOverlap([
    { referenceId: "a", timelineStart: 0, timelineEnd: 5, sourceStart: 0, sourceEnd: 5 },
    { referenceId: "b", timelineStart: 4, timelineEnd: 8, sourceStart: 0, sourceEnd: 4 },
  ])).toBe(true);
});
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `npm test -- --run src/features/agent-canvas/editing/editingTimelineMath.test.ts src/features/agent-canvas/editing/editingPlayableSequence.test.ts`

Expected: FAIL because the explicit-position helpers and fixed-duration sequence behavior do not exist.

- [ ] **Step 3: Implement the minimal explicit-position model**

Use the persisted start when present, otherwise use the current compatibility fallback only for legacy manifests:

```ts
export interface TimelineClipInput {
  referenceId: string;
  sourceDuration: number;
  trimStart: number;
  trimEnd: number | null;
  timelineStart?: number;
}

export function buildTimelineSegments(
  clips: readonly TimelineClipInput[],
  timelineDuration?: number,
): TimelineSegment[] {
  let legacyStart = 0;
  return clips
    .map((clip) => {
      const range = normalizeTrimRange(clip.sourceDuration, clip.trimStart, clip.trimEnd ?? clip.sourceDuration);
      const duration = editedClipDuration(clip.sourceDuration, range.start, range.end);
      const timelineStart = Math.max(0, finiteOr(clip.timelineStart ?? legacyStart, legacyStart));
      legacyStart = timelineStart + duration;
      return {
        referenceId: clip.referenceId,
        timelineStart,
        timelineEnd: timelineStart + duration,
        sourceStart: range.start,
        sourceEnd: range.start + duration,
      };
    })
    .sort((left, right) => left.timelineStart - right.timelineStart);
}

export function clampTimelineStart(start: number, duration: number, timelineDuration: number): number {
  return Math.max(0, Math.min(Math.max(0, timelineDuration - duration), finiteOr(start, 0)));
}

export function hasTimelineOverlap(segments: readonly TimelineSegment[]): boolean {
  return [...segments]
    .sort((left, right) => left.timelineStart - right.timelineStart)
    .some((segment, index, sorted) => index > 0 && segment.timelineStart < sorted[index - 1]!.timelineEnd);
}
```

The compatibility fallback is only for reading old manifests. New drag commits must always use an explicit timeline start and must not rewrite other entries.

- [ ] **Step 4: Update the playable sequence**

Keep the fixed timeline duration independent from the last clip:

```ts
const timelineDuration = content.manifest.timeline_duration_seconds
  ?? inputs.reduce((total, input) => total + (input.asset?.duration_seconds ?? 0), 0);
const segments = buildTimelineSegments(
  videos.map((input) => ({
    referenceId: input.referenceId,
    sourceDuration: input.asset?.duration_seconds ?? input.entry.trim_end_seconds ?? input.entry.trim_start_seconds + 0.5,
    trimStart: input.entry.trim_start_seconds,
    trimEnd: input.entry.trim_end_seconds,
    timelineStart: input.entry.timeline_start_seconds,
  })),
  timelineDuration,
);
return { videos, inactiveVideos, segments, duration: timelineDuration };
```

For old manifests, the fallback duration is the original total source duration, not the sum of trimmed durations.

- [ ] **Step 5: Run the focused tests and verify they pass**

Run: `npm test -- --run src/features/agent-canvas/editing/editingTimelineMath.test.ts src/features/agent-canvas/editing/editingPlayableSequence.test.ts`

Expected: PASS, with old contiguous-manifest tests updated only where the fixed-duration compatibility behavior changes.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/types-v2.ts apps/web/src/features/agent-canvas/model/normalizers.ts apps/web/src/features/agent-canvas/editing/editingTimelineMath.ts apps/web/src/features/agent-canvas/editing/editingPlayableSequence.ts apps/web/src/features/agent-canvas/editing/editingTimelineMath.test.ts apps/web/src/features/agent-canvas/editing/editingPlayableSequence.test.ts
git commit -m "feat: model fixed single-track editing positions"
```

### Task 2: Replace reorder-only dragging with free single-track placement

**Files:**
- Modify: `apps/web/src/features/agent-canvas/editing/EditingTimeline.tsx`
- Modify: `apps/web/src/features/agent-canvas/editing/VideoTimelineClip.tsx`
- Modify: `apps/web/src/features/agent-canvas/editing/editingModel.ts`
- Modify: `apps/web/src/features/agent-canvas/editing/agent-canvas-editing.css`
- Test: `apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx`

**Interfaces:**
- Replace `onStageVideoOrder` and reorder-only drag state with `onStageVideo(referenceId, { timeline_start_seconds })` during preview.
- `VideoTimelineClip` body pointer interaction reports a free horizontal drag; trim handles retain their existing independent source-range drag behavior.
- A body drag uses the segment's initial `timelineStart`, converts `deltaX / pixelsPerSecond` to seconds, clamps to `[0, timelineDuration - clipDuration]`, and rejects positions that overlap another clip.

- [ ] **Step 1: Write failing component tests**

```tsx
it("moves a clip freely on the fixed track and commits its timeline start once", () => {
  const inputs = {
    videos: [
      video("video-a", 1, { timeline_start_seconds: 0 }),
      video("video-b", 2, { timeline_start_seconds: 12 }),
    ],
    bgm: null,
  };
  const callbacks = renderTimeline({ inputs, selectedReferenceId: "video-b" });
  const clip = screen.getByRole("button", { name: "Select Shot 2" });

  fireEvent.pointerDown(clip, { pointerId: 11, clientX: 120 });
  fireEvent.pointerMove(window, { pointerId: 11, clientX: 70 });
  expect(callbacks.onStageVideo).toHaveBeenCalledWith("video-b", { timeline_start_seconds: expect.any(Number) });
  expect(callbacks.onCommitStagedManifest).not.toHaveBeenCalled();

  fireEvent.pointerUp(window, { pointerId: 11, clientX: 70 });
  expect(callbacks.onCommitStagedManifest).toHaveBeenCalledTimes(1);
});

it("keeps a valid gap after a trim without moving the next clip", () => {
  const inputs = {
    videos: [
      video("video-a", 1, { timeline_start_seconds: 0, trim_start_seconds: 1, trim_end_seconds: 5 }),
      video("video-b", 2, { timeline_start_seconds: 10 }),
    ],
    bgm: null,
  };
  renderTimeline({ inputs });
  expect(screen.getByTestId("timeline-clip-video-a").style.left).toBe("0px");
  expect(screen.getByTestId("timeline-clip-video-b").style.left).toContain("10");
});

it("does not commit a body drag that would overlap another clip", () => {
  const callbacks = renderTimeline({
    inputs: {
      videos: [video("video-a", 1, { timeline_start_seconds: 0 }), video("video-b", 2, { timeline_start_seconds: 12 })],
      bgm: null,
    },
  });
  const clip = screen.getByRole("button", { name: "Select Shot 2" });
  fireEvent.pointerDown(clip, { pointerId: 12, clientX: 120 });
  fireEvent.pointerMove(window, { pointerId: 12, clientX: 20 });
  fireEvent.pointerUp(window, { pointerId: 12, clientX: 20 });
  expect(callbacks.onCommitStagedManifest).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the component tests and verify they fail**

Run: `npm test -- --run src/features/agent-canvas/editing/EditingTimeline.test.tsx`

Expected: FAIL because the timeline currently interprets body dragging as array reordering and does not render explicit gaps.

- [ ] **Step 3: Implement single-track body dragging**

In `EditingTimeline`, keep a pointer session containing the initial timeline start, the selected clip duration, and the other clip segments. During pointer movement:

```ts
const proposedStart = clampTimelineStart(
  initial.timelineStart + (pointerEvent.clientX - startClientX) / pixelsPerSecond,
  clipDuration,
  sequenceDuration,
);
const proposedSegment = { ...initial, timelineStart: proposedStart, timelineEnd: proposedStart + clipDuration };
const occupied = segments.filter((segment) => segment.referenceId !== referenceId);
if (hasTimelineOverlap([...occupied, proposedSegment])) {
  setClipDrag({ ...current, invalid: true, previewStart: proposedStart });
  return;
}
setClipDrag({ ...current, invalid: false, previewStart: proposedStart });
onStageVideo(referenceId, { timeline_start_seconds: roundTimeline(proposedStart) });
```

On pointer release, commit exactly once only for a valid moved position. On Escape or pointer cancellation, discard the staged manifest. Remove insertion indicators and reorder callbacks. Keep clip DOM `left` derived from `segment.timelineStart` and apply the preview offset only to the dragged clip.

Add `data-testid="timeline-clip-${referenceId}"` to the clip root for stable tests. Add an `aria-invalid` state and a restrained red/gray invalid drop treatment; it must not mutate the manifest.

- [ ] **Step 4: Keep trim independent from placement**

Ensure `VideoTimelineClip` stages only `trim_start_seconds` or `trim_end_seconds` for trim handles. Its rendered `left` comes from the segment's timeline start, and a left trim must never update `timeline_start_seconds`. A right trim must never update any other entry.

- [ ] **Step 5: Run focused tests and verify they pass**

Run: `npm test -- --run src/features/agent-canvas/editing/EditingTimeline.test.tsx`

Expected: PASS, including existing trim cancel, commit-on-release, frame strip, and selected-handle tests.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/EditingTimeline.tsx apps/web/src/features/agent-canvas/editing/VideoTimelineClip.tsx apps/web/src/features/agent-canvas/editing/editingModel.ts apps/web/src/features/agent-canvas/editing/agent-canvas-editing.css apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx
git commit -m "feat: allow free single-track clip placement"
```

### Task 3: Persist fixed duration and placement through the existing manifest commit queue

**Files:**
- Modify: `apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.ts`
- Modify: `apps/web/src/features/agent-canvas/editing/editingModel.ts`
- Test: `apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx`
- Test: `apps/web/src/features/agent-canvas/editing/editingModel.test.ts`

**Interfaces:**
- Preserve the current coalesced manifest commit coordinator, ETag/If-Match behavior, conflict recovery, and optimistic local draft behavior.
- `stageVideoUpdate(referenceId, { timeline_start_seconds })` must produce a canonical manifest patch; no separate local position store is allowed.
- `buildPlayableEditingSequence` must use the fixed manifest duration so playhead and ruler remain stable after trim or move.

- [ ] **Step 1: Write failing hook/model tests**

```tsx
it("serializes a free clip move without changing the other entries", async () => {
  const { result } = renderHook(() => useAgentCanvasEditing(makeEditingProps()));
  act(() => result.current.stageVideoUpdate("binding-video-2", { timeline_start_seconds: 5 }));
  await act(async () => { await result.current.commitStagedManifest(); });
  expect(patchNode).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
    structured_content: expect.objectContaining({
      manifest: expect.objectContaining({
        video_entries: expect.arrayContaining([
          expect.objectContaining({ binding_id: "binding-video-2", timeline_start_seconds: 5 }),
        ]),
      }),
    }),
  }), expect.anything());
});
```

- [ ] **Step 2: Run the focused hook/model tests and verify they fail**

Run: `npm test -- --run src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx src/features/agent-canvas/editing/editingModel.test.ts`

Expected: FAIL because the current manifest entry type and update fixture do not carry timeline positions.

- [ ] **Step 3: Implement manifest-preserving updates**

Extend `updateEditingVideoEntry` to merge `timeline_start_seconds` without rebuilding or reordering entries. Preserve `timeline_duration_seconds` when replacing or staging manifests. Keep all commit retries and conflict paths unchanged.

When reading a legacy manifest with no fixed duration, establish the fixed duration from the original source total in the sequence layer; do not use the trimmed end as the ruler duration. Do not silently add a position field to an API payload when the backend contract has not been updated in the running environment; the integration flag must be explicit and default off until the backend exposes the field. This limitation must be surfaced in the final report.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `npm test -- --run src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx src/features/agent-canvas/editing/editingModel.test.ts`

Expected: PASS with existing ETag conflict, coalescing, discard, export barrier, and optimistic draft tests preserved.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.ts apps/web/src/features/agent-canvas/editing/editingModel.ts apps/web/src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx apps/web/src/features/agent-canvas/editing/editingModel.test.ts
git commit -m "feat: persist editing timeline placement through manifest updates"
```

### Task 4: Verify preview, ruler, gaps, and regression coverage

**Files:**
- Modify: `apps/web/src/features/agent-canvas/editing/EditingPreviewStage.tsx`
- Modify: `apps/web/src/features/agent-canvas/editing/editingTimelineVisibility.ts`
- Modify: `apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/editing/EditingPreviewStage.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/editing/agent-canvas-editing.css`

**Interfaces:**
- Timeline preview maps fixed-time playhead to the clip containing that time; during a gap, no video clip is selected and the preview remains on the existing empty/black state.
- Frame-strip visibility uses explicit segment positions and must not mark a clip active merely because it is adjacent in the manifest array.
- The playhead remains clamped to the fixed duration and stays above both tracks.

- [ ] **Step 1: Write failing gap and fixed-duration tests**

```tsx
it("keeps the playhead and ruler at the original total duration after trim", () => {
  renderTimeline({
    inputs: {
      videos: [video("video-a", 1, { timeline_start_seconds: 0, trim_start_seconds: 3, trim_end_seconds: 4 })],
      bgm: null,
    },
  });
  expect(screen.getByRole("slider", { name: "Timeline playhead" }).getAttribute("aria-valuemax")).toBe("10");
});

it("shows a timeline gap instead of stretching the neighboring clip", () => {
  const inputs = {
    videos: [video("video-a", 1, { timeline_start_seconds: 0, trim_end_seconds: 4 }), video("video-b", 2, { timeline_start_seconds: 8 })],
    bgm: null,
  };
  renderTimeline({ inputs });
  expect(screen.getByTestId("timeline-clip-video-b").getAttribute("style")).toContain("left:");
});
```

- [ ] **Step 2: Run the focused timeline and preview tests and verify failures identify the old contiguous assumptions**

Run: `npm test -- --run src/features/agent-canvas/editing/EditingTimeline.test.tsx src/features/agent-canvas/editing/EditingPreviewStage.test.tsx`

- [ ] **Step 3: Update preview and visibility calculations**

Use the explicit segments to resolve the playhead. Do not change the existing preview media element lifecycle or audio synchronization behavior. A gap must not cause the next clip to start early, and an out-of-range move must not clip the rendered card.

- [ ] **Step 4: Run all affected Editing tests**

Run: `npm test -- --run src/features/agent-canvas/editing`

Expected: PASS for all existing and new focused tests.

- [ ] **Step 5: Run typecheck, lint, and build**

Run: `npm run typecheck && npm run lint:react && npm run lint && npm run build`

Expected: all commands exit with code 0.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/agent-canvas/editing/EditingPreviewStage.tsx apps/web/src/features/agent-canvas/editing/editingTimelineVisibility.ts apps/web/src/features/agent-canvas/editing/EditingTimeline.test.tsx apps/web/src/features/agent-canvas/editing/EditingPreviewStage.test.tsx apps/web/src/features/agent-canvas/editing/agent-canvas-editing.css
git commit -m "test: verify fixed editing timeline gaps"
```

## Backend Contract Gate

The current canonical backend defines `EditingVideoEntryV2` with `trim_start_seconds` and `trim_end_seconds`, but rejects unknown fields. Before enabling durable free placement, the backend must add and validate `timeline_start_seconds` on each video entry and define where the fixed `timeline_duration_seconds` is stored. The frontend must then consume the final OpenAPI schema, remove the compatibility guard, and run a live refresh/export smoke test. Until that contract is merged, the frontend branch may validate the interaction model with mocked manifest responses, but it must not send unsupported fields to the running backend or claim that free positions persist or affect real exports.
