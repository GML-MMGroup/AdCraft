# Professional Editing Timeline Design

## Summary

Upgrade the Agent Canvas Editing panel from a form-oriented composition editor into a timeline-oriented video editor while preserving the existing canonical Editing manifest, Export, Download, Add to Canvas, conflict handling, and backend authority.

The redesign adds:

- a complete, uncropped preview stage;
- real frame strips for video clips;
- direct left/right trim handles;
- a shared zoomable time coordinate system;
- a real audio waveform presentation;
- local drag previews with silent persistence on pointer release.

The frontend does not add a browser-side render pipeline or FFmpeg integration. Final composition and export remain backend-owned.

## Goals

1. Show 16:9, 9:16, 1:1, and other output shapes completely inside the preview area.
2. Make trimming a direct manipulation on the video clip instead of numeric `Trim start` and `Trim end` fields.
3. Show representative frames across each clip so users can trim by visual content.
4. Present the audio track as a professional waveform aligned to the same timeline as video.
5. Preserve all existing Editing behavior, including clip order, enabled state, source audio, volume, transitions, fit mode, output settings, Export, cancel, Download, Add to Canvas, warnings, omitted inputs, and errors.
6. Keep backend writes efficient and authoritative.

## Non-goals

- Browser-side final rendering or FFmpeg.
- Changing the Editing manifest schema or adding backend endpoints.
- Frame-accurate transition compositing in the browser.
- Multi-track compositing beyond the canonical ordered video sequence and optional BGM.
- Destructive changes to source assets.

## Chosen Approach

Use React DOM for the timeline, Pointer Events for direct manipulation, HTML media elements for draft playback, Canvas for frame extraction and waveform rendering, and the existing Node PATCH path for persistence.

This approach fits the current editing components and expected workflow size better than a WebGL editor. It also provides accessible controls and avoids decorative poster repetition that would not represent actual video content.

## Component Architecture

### `AgentCanvasEditingPanel`

Remains the composition shell and owns header actions, output settings, warnings, omitted inputs, and Export lifecycle. It composes the new preview and timeline modules instead of containing their media interaction logic.

### `EditingPreviewStage`

Responsibilities:

- derive the output frame ratio from `manifest.output.aspect_ratio`, resolution, or active media metadata;
- fit that complete frame into the available preview area;
- render the active timeline source at the playhead position;
- synchronize play, pause, seek, mute, and BGM preview;
- preserve the exported-video preview when appropriate;
- expose a black letterbox area rather than cropping the output frame.

The outer stage uses a stable aspect-ratio-constrained viewport. The visible video uses `object-fit: contain`. Per-clip `fit_mode` remains an export property; the editor itself never crops the complete output frame from the preview panel.

### `EditingTimelineViewport`

Owns:

- horizontal scrolling;
- pixels-per-second scale;
- fit-all calculation;
- zoom slider and zoom buttons;
- ruler ticks;
- playhead positioning;
- conversion between screen X coordinates and timeline seconds.

Every lane receives the same scale and content width. Video clips, trim handles, frame thumbnails, audio waveform, ruler, and playhead therefore cannot drift onto different time coordinates.

### `VideoTrack` and `VideoTimelineClip`

Each clip is positioned from its cumulative edited duration. A clip contains:

- a real sampled frame strip;
- clip name and edited duration;
- selected and disabled states;
- left and right trim handles;
- compact access to retained clip properties.

Changing a trim boundary immediately changes the local clip width and shifts subsequent clips in the draft timeline.

### `TrimHandle`

Each selected clip has left and right bars with a generous pointer hit target. The visible bar remains narrow and professional.

Rules:

- handles cannot cross;
- minimum edited duration is `0.5s`, matching current timeline behavior;
- source boundaries clamp to `[0, sourceDuration]`;
- the left handle updates `trim_start_seconds`;
- the right handle updates `trim_end_seconds`;
- a floating time label displays the source time while dragging;
- the playhead follows the dragged boundary so the preview shows the exact frame being selected.

### `VideoFrameStrip`

Extracts actual frames from each source video with a hidden media element and Canvas.

Sampling policy:

- sample only clips intersecting the visible timeline range plus one adjacent viewport;
- calculate frame density from visible clip width, not source duration alone;
- reuse cached samples keyed by asset ID, rounded source time, and thumbnail size;
- cap concurrent media seeking and Canvas extraction;
- pause new work while the document is hidden;
- fall back to `preview_url` when frame extraction is unavailable.

The frame cache is in-memory UI data and is never written to the workflow.

### `AudioWaveformTrack`

Fetches and decodes the canonical audio asset once with Web Audio, downsamples it into peak buckets, and renders a mirrored waveform aligned to the shared timeline width.

The track header retains audio name, mute, and volume controls. Fade and trim properties remain available in a compact properties toolbar. If decoding fails, the track displays a restrained deterministic fallback instead of blocking Editing.

### `ClipPropertiesToolbar`

Replaces the large `Selected clip` form.

It retains:

- enabled state;
- move earlier/later;
- clip volume;
- preserve native audio;
- transition type and duration;
- fit mode.

It does not contain numeric trim start/end fields. Trimming belongs exclusively to direct manipulation on the timeline.

### `useEditingTimelineDraft`

Owns transient interaction state independently from the canonical Editing manifest:

- active drag;
- local trim values;
- latest confirmed values;
- pending commit generation;
- rollback after a failed save.

This keeps pointer movement out of the backend mutation hook and prevents the main panel from becoming a stateful monolith.

## Timeline Coordinate Model

The timeline uses one `pixelsPerSecond` value.

```text
contentWidth = max(viewportWidth, timelineDuration * pixelsPerSecond)
x(seconds) = seconds * pixelsPerSecond
seconds(x) = x / pixelsPerSecond
```

The minimum zoom is the fit-all scale. The maximum scale is capped to keep frame extraction and DOM width bounded. Zoom is anchored to the playhead for buttons and to the pointer time for `Ctrl/Command + wheel`, preventing the content under the pointer from jumping.

Interaction:

- ordinary wheel/trackpad input scrolls horizontally inside the timeline;
- `Ctrl/Command + wheel` zooms;
- minus, slider, plus, and fit-all controls provide explicit zoom;
- double-clicking the ruler restores fit-all;
- keyboard arrow keys move the playhead when the timeline is focused.

## Trim Persistence and Concurrency

Dragging is local-only. Pointer movement never sends PATCH requests.

On pointer release:

1. finalize the local trim values;
2. enqueue one silent manifest update;
3. keep the local draft visible while the request is in flight;
4. mark the values confirmed when the canonical update succeeds;
5. show an error and restore the last confirmed values if the update fails and no newer local edit exists.

There is no Apply button and no success toast.

Commits are serialized per Editing node. If the user releases a handle again while a previous save is in flight, only the newest pending manifest is sent after the active request settles. Older responses cannot clear or overwrite a newer local draft.

Export remains disabled while an Editing manifest save is unresolved so the backend cannot export a manifest older than the timeline the user sees.

## Draft Preview Behavior

The browser provides a responsive editorial preview, not an authoritative final render.

- The playhead maps to the active ordered clip.
- Source playback time is `trim_start_seconds + offsetWithinClip`.
- Crossing a clip boundary switches to the next source.
- BGM preview follows the same playhead and respects enabled, trim, and volume values.
- Transition and final mix fidelity remain backend-owned.

The final exported asset remains available for authoritative playback. The UI labels draft timeline playback and exported output clearly enough that the user does not mistake the draft preview for a completed export.

## Visual Direction

Continue the existing black, white, and gray editor language:

- near-black workspace and track canvas;
- graphite track headers;
- white playhead and selected trim bars;
- restrained gray borders;
- no gradients, ornamental glow, or colorful timeline categories;
- stable row heights and compact typography;
- icon buttons for transport, zoom, mute, ordering, and fit actions.

Selection is communicated by contrast and the trim handles, not a large decorative outline. The audio waveform is neutral gray with a brighter played region.

## Error and Degraded States

- Frame extraction failure: use the canonical preview image for that clip.
- Audio decode failure: show a non-blocking fallback waveform and keep audio controls available.
- Missing duration metadata: load media metadata before enabling trim; preserve the clip in the sequence meanwhile.
- Save conflict or ETag failure: use the existing conflict path, restore canonical values, and explain that the composition changed elsewhere.
- Export in progress: timeline controls are read-only; playback, scrolling, and zoom remain available.
- Media URL unavailable: keep the clip visible with its name, duration if known, and media-type icon.

## Accessibility

- Trim handles use slider semantics and keyboard adjustment.
- The timeline exposes current playhead time and zoom.
- Icon buttons have names and tooltips.
- Dragging is not the only way to adjust trim: selected handles support arrow-key increments and Shift-modified larger increments.
- `prefers-reduced-motion` disables animated scrolling and nonessential transitions without changing editing behavior.

## Test Strategy

Focused unit and component coverage will verify:

1. timeline seconds-to-pixels mapping and fit/zoom math;
2. trim clamping and minimum duration;
3. no mutation during pointer movement;
4. exactly one commit on pointer release;
5. serial coalescing of rapid successive releases;
6. rollback on save failure without overwriting a newer draft;
7. complete preview sizing for landscape, portrait, and square output;
8. frame sampling and poster fallback;
9. waveform peak reduction and decode fallback;
10. retention of existing output settings, Export, cancel, Download, Add to Canvas, omitted-input, warning, and conflict behavior.

After focused tests, run frontend typecheck, lint, and build once. Visual verification should cover desktop editor sizes and both landscape and portrait video assets.

## Implementation Sequence

1. Extract timeline math and trim draft state with tests.
2. Build the shared zoomable timeline viewport.
3. Add direct trim handles and silent serialized commits.
4. Add video frame sampling and caching.
5. Add waveform extraction and the redesigned audio lane.
6. Build the complete preview stage and draft playback mapping.
7. Rehome existing clip and output controls.
8. Complete focused, type, lint, build, and visual verification.
