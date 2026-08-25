# Task 6 Report: Complete Preview Stage and Draft Playback Mapping

## Status

Implemented Task 6 and fix round 1. The timeline, panel transport, draft preview, and BGM now share one filtered playable sequence; inactive authoring sources remain available off the timed track.

## Delivered

- Added `EditingPreviewStage.tsx` with ratio precedence from output aspect ratio, output resolution, exported dimensions, active source dimensions, and a 16:9 fallback.
- Added pure `fitContainedFrame()` sizing and a `ResizeObserver`-driven workspace measurement. The stage sets explicit contained width and height for landscape, portrait, and square outputs while source/export media remain `object-fit: contain`, independent of per-clip `fit_mode`.
- Added `buildPlayableEditingSequence()` as the single ordered sequence authority. Only enabled entries with a ready asset/media URL and a null-or-ready source node contribute segments, timeline duration, draft boundaries, transport duration, and BGM timing.
- Added a compact untimed Inactive sources region. Disabled entries can be re-enabled; unavailable entries expose their status, remain selectable, and retain the existing properties/actions.
- Remounts the draft video for every reference/media URL load with an immutable generation token on the DOM element. Media handlers validate the render-captured token against `event.currentTarget.dataset` and the committed token, so stale events after switches or clears cannot mutate playback.
- Synchronized BGM with a 0.2-second tolerance, including trim start/end, enabled state, volume, mute, unbounded source looping, and swallowed autoplay failures.
- Snapped playback to the exact final timeline boundary, stopped transport there, clamped playhead state after trim shortening, and reset short sequences correctly for replay.
- Added complete Draft preview and Exported output tabs with linked tab panels, roving `tabIndex`, and ArrowLeft/ArrowRight/Home/End navigation. Export playback uses independent native controls and does not replace the controlled draft playhead.
- Removed preview refs and direct media synchronization from `AgentCanvasEditingPanel`; its existing transport now controls draft state and remains usable without an exported asset.
- Preserved the export progress overlay, Download/Add to Canvas actions, output controls, timeline controls, and transport labels.

## TDD Evidence

1. Added the preview-stage suite first. The initial run failed because `EditingPreviewStage.tsx` did not exist.
2. Implemented ratio containment, two-clip mapping, BGM synchronization, timeline-end stopping, autoplay handling, and export view; the suite passed 7/7.
3. Added a panel regression requiring source playback without an export. It failed because transport was still gated on `outputAsset`, then passed after stage integration.
4. Self-review added regressions for unavailable-export ratio metadata, paused BGM seeking, trim-shortening clamps, and stale `ended` events. All four failed before their fixes and passed afterward.
5. Added regressions for short-sequence replay, unbounded BGM looping, and export-view draft transport. Each exposed the corresponding edge case before the final implementation.
6. Fix round 1 started with failing sequence tests showing disabled/unavailable clips consumed timed-track duration, then introduced the shared playable sequence.
7. Added stale switch/clear event tests before replacing mutable source checks with keyed generation tokens.
8. Added six pure containment cases plus a ResizeObserver integration test before implementing explicit frame dimensions.
9. Added linked tab-panel and keyboard-navigation assertions before completing tab semantics.
10. Added rejected-BGM playback coverage and a zero-playable-duration BGM regression. The latter failed with one transient `play()` call before BGM synchronization was gated on active sequence duration.

## Verification

From `apps/web`:

```text
npm test -- --run editingModel editingTimelineMath editingPlayableSequence useAgentCanvasEditing useVideoFrameStrip useAudioWaveform EditingTimeline EditingPreviewStage AgentCanvasEditingPanel
9 files passed, 108 tests passed

npm run typecheck
passed

npx eslint src/features/agent-canvas/editing/AgentCanvasEditingPanel.tsx src/features/agent-canvas/editing/EditingPreviewStage.tsx src/features/agent-canvas/editing/EditingPreviewStage.test.tsx src/features/agent-canvas/editing/EditingTimeline.tsx src/features/agent-canvas/editing/EditingTimeline.test.tsx src/features/agent-canvas/editing/editingPlayableSequence.ts src/features/agent-canvas/editing/editingPlayableSequence.test.ts src/features/agent-canvas/editing/editingPreviewSizing.ts
passed

npm run build
passed (793 modules transformed)
```

`git diff --check` passed during self-review.

## Self-Review

- Confirmed the ratio precedence matches the required order, including export dimensions when export media is not yet readable, and that every measured frame fits both workspace bounds.
- Confirmed all timed consumers receive the same compressed playable sequence and inactive sources remain editable outside timeline time.
- Confirmed clip URL/reference changes remount the video and stale `loadedmetadata`, `timeupdate`, and `ended` events cannot advance a new or cleared load.
- Confirmed play promises are guarded by attempt identity so an old rejection cannot stop a newer clip.
- Confirmed BGM remains independently synchronized and a BGM autoplay rejection cannot stop video playback.
- Confirmed final export playback is labeled and independently controlled while returning to Draft preview restores source mapping from the unchanged playhead.
- Confirmed transport duration uses trimmed sequence duration, including the 0.5-second minimum clip case.

## Concerns

- Draft playback intentionally does not reproduce transitions or the final FFmpeg mix; Exported output remains the authoritative result.
- Browser codec support and autoplay policy can prevent a source or BGM element from playing. The stage keeps controlled state coherent and treats BGM failure as non-fatal, but it cannot bypass browser policy.
- Inactive source status is derived from current node/asset availability; it updates when the parent editing inputs refresh.
