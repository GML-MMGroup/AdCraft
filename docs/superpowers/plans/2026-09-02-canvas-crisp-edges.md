# Canvas crisp edge rendering plan

## Goal

Make every workflow edge remain visually continuous and clear across the full React Flow zoom range, while keeping every edge visible, below node cards, and compatible with the existing drag-performance optimizations.

## Design

- Keep React Flow's SVG edge layer and existing edge data, selection, deletion, arrows, and frozen-during-drag overlay.
- Remove `vector-effect: non-scaling-stroke`; edge geometry and stroke will be transformed together by the viewport.
- Maintain a stable screen-pixel target by updating a CSS custom property from the React Flow viewport callback. This update is DOM-only and coalesced with `requestAnimationFrame`, so zooming does not rebuild React edge arrays.
- Clamp world-space stroke width to a safe range so edges are neither too heavy when zoomed out nor excessively thick when zoomed in.
- Use opaque neutral gray for the normal edge and explicit opaque hover/selected colors. Use `butt` caps and `geometricPrecision` to reduce rounded-cap and alpha accumulation artifacts.
- Set `.react-flow__edges` below `.react-flow__nodes`; keep the frozen overlay at the same lower layer and non-interactive.
- Keep viewport compositing only during active pan/zoom/drag; restore normal compositing after interaction.

## Implementation steps

1. Add a small pure edge-zoom model that maps viewport zoom to world-space stroke width and exposes the allowed clamp/target values.
2. Add a DOM-only viewport style synchronizer, wire it to `onInit`, `onMove`, and `onMoveEnd`, and avoid React state updates.
3. Update edge CSS and marker colors/layering without changing edge visibility or data construction.
4. Add unit and browser-facing assertions for zoom buckets, edge count, stroke styles, and layer order.
5. Run focused tests, typecheck, lint, production build, and a real browser check against `adwf_v2_1ce0210d9406de73` at zoom 0.05, 0.10, 0.16, 0.25, 0.50, 1, 1.5, and 2.

## Acceptance criteria

- All backend edge data remains intact; every edge in the current React Flow render and every frozen drag edge remains visible at each tested zoom (viewport culling may still omit edges outside the rendered viewport, as in the existing performance configuration).
- Edge stroke follows zoom without the previous fixed-width haze or excessive low-zoom thickness.
- Edges render below node cards and cannot cover node content.
- Existing drag freeze, edge selection/highlight, deletion, and arrow markers still work.
- No additional React Flow edge-array rebuild is introduced during viewport movement.
- Existing canvas performance behavior is preserved.
