# Workflow Interaction and Media Preview Design

## Goal

Improve the Workflow canvas experience for the historical workflow `adwf_v2_1ce0210d9406de73` without changing backend contracts or removing visible connections. The change addresses four observed issues: canvas pan lag, node drag lag, blurry edges at minimum zoom, and video nodes with no backend poster failing to show a preview.

## Constraints

- Work only in the frontend repository.
- All edges remain visible during node dragging. Connected edges continue to follow dragged nodes; frozen edges remain visible through the existing overlay.
- Preserve the existing viewport transform, progressive reveal, drag projection, media defer, and pointer-spotlight suspension behavior.
- Do not eagerly download every video. A video with a backend poster uses that rendition; a video without one may load source metadata and capture a poster only after its node is near the viewport.
- Do not change API contracts or infer a backend rendition that is not present.

## Design

### Canvas interaction and edges

The canvas keeps React Flow's single viewport transform and the existing RAF-batched controlled node updates. During interaction, the existing `is-interacting` class continues to suspend pointer spotlight and expensive node effects. Base edge paint is simplified by removing the drop shadow, increasing the base stroke opacity, and using `vector-effect: non-scaling-stroke`. This keeps SVG paths legible when the viewport is zoomed out and reduces filter paint work during pan and drag. Selected and related edges retain their distinct dashed animation while also avoiding drop-shadow blur; the existing interaction rule pauses that animation. No edge is hidden.

### Video previews

`MediaSurface` will use a small `CanvasVideoPreview` component for video assets. It first renders a backend poster/preview through `StableMediaPreview` when available. When no derived poster exists, it renders a muted native video element with `preload="none"` and no `src` until an IntersectionObserver reports that the node is within a generous prefetch margin. At that point it assigns the immutable `mediaAssetContentPath(asset)` URL, switches to metadata preload, requests a near-first frame, and lets `useAgentCanvasVideoPoster` persist a cached poster. The native element remains a fallback if poster extraction fails. The play affordance and existing dialog callback remain unchanged.

The fallback component is isolated so only poster-less video nodes pay the native-video cost, and offscreen nodes do not start network or decode work. It uses `pointer-events: none` for the video surface so node dragging remains unaffected.

Poster-less source activation goes through a small FIFO scheduler with one active source load at a time. A completed, failed, or timed-out load releases the slot for the next eligible node. This prevents a historical canvas with several full-size videos from saturating the browser while preserving eventual previews.

### Verification

Tests cover the CSS invariants, the poster-less video fallback, lazy source activation, and preservation of the existing backend-poster path. Browser verification uses the historical project route to check edge computed styles at minimum zoom, all edge elements after a node drag, and a poster-less video node transitioning from an inert preview to a source-backed preview when intersecting.
