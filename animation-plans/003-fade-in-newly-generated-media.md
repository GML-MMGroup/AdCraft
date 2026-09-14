# 003 — Fade in newly generated media only

- **Status**: DONE
- **Commit**: f5aa1e4f
- **Severity**: LOW
- **Category**: Missed opportunity; Easing & duration
- **Estimated scope**: 5 files, approximately 140 lines

## Problem

While an image or video node is working, its normal media surface is intentionally unmounted:

```tsx
/* apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx:254 — current */
<div className="agent-canvas-node__surface">
  {!generatingMediaType ? <NodeSurface ... /> : null}
  {generatingMediaType ? (
    <AgentCanvasMediaGenerationLoader mediaType={generatingMediaType} />
  ) : null}
</div>
```

When the authoritative node becomes `ready`, the Loader disappears and the new media mounts. Once the image finishes loading, it appears at full opacity immediately. A generic mount animation is not acceptable because React Flow culls offscreen nodes; already-loaded historical media would then fade from blank whenever its node remounts.

## Target

Apply a `160ms cubic-bezier(0.23, 1, 0.32, 1)` opacity entrance only when all conditions hold:

1. The same mounted node transitioned from `working` to `ready`.
2. The new image/poster fired its native `load` event.
3. The transition token still matches that node and output asset.

Initial `ready` nodes, viewport remounts, cached historical cards, ordinary rerenders, and Prompt/status changes that do not pass through `working → ready` must render immediately at opacity `1`.

Add this CSS:

```css
.agent-canvas-node__media--awaiting-generation-reveal {
  opacity: 0;
}

.agent-canvas-node__media--generation-revealed {
  animation: agent-canvas-node-media-reveal 160ms cubic-bezier(0.23, 1, 0.32, 1) both;
}

@keyframes agent-canvas-node-media-reveal {
  from { opacity: 0; }
  to { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .agent-canvas-node__media--generation-revealed {
    animation: none;
    opacity: 1;
  }
}
```

Use a transition token shaped as:

```ts
`${node.node_id}:${node.output_asset_id ?? "pending-output"}`
```

`AgentCanvasNodeCard` must retain the token when it observes `working → ready`, including the case where the Asset summary arrives on a later render. Use `useLayoutEffect` plus the previous status ref so the ready surface cannot paint before the reveal intent is installed.

Extend `CanvasMediaPreview` with:

```ts
revealToken?: string | null;
```

It must track the last loaded reveal token, append `agent-canvas-node__media--awaiting-generation-reveal` while the matching image has not loaded, and append `agent-canvas-node__media--generation-revealed` only after the native `load` event. It must still call the caller's existing `onLoad` handler exactly once.

Pass the token through `NodeSurface`, `MediaSurface`, and `CanvasVideoPreview` so image results and generated video posters behave identically.

## Repo conventions to follow

- `CanvasMediaPreview` remains the cache-aware canvas wrapper around `StableMediaPreview`.
- `StableMediaPreview` may initially render with no `src` for a versioned cache miss, so the fade must begin on native `load`, not component mount.
- Existing media dimensions callbacks in `MediaSurface` and `CanvasVideoPreview` must remain unchanged.
- The strong UI entrance curve already used by chat is `cubic-bezier(0.23, 1, 0.32, 1)`.

## Steps

1. Add `CanvasMediaPreview.test.tsx` cases for no-token immediate display, token-pending opacity class, load-triggered reveal class, source/token replacement, and exactly-once forwarding of `onLoad`.
2. Add `AgentCanvasNode.test.tsx` cases that rerender one node from `working` to `ready`, verify the reveal token reaches image and video poster paths, and verify a node initially mounted as `ready` has no reveal classes.
3. Add a remount regression test: unmount and remount an already-ready card and confirm it never receives the awaiting class.
4. Run focused tests and confirm failures against the current instant-swap implementation.
5. Implement `revealToken` state/class handling in `CanvasMediaPreview.tsx` without changing `StableMediaPreview.tsx`.
6. Add the previous-status ref and generation reveal token in `AgentCanvasNodeCard`, then thread the optional token through `NodeSurface`, `MediaSurface`, and `CanvasVideoPreview`.
7. Add the exact CSS and reduced-motion override above.
8. Run focused tests, typecheck, ESLint, and build.

## Boundaries

- Do NOT keep old media mounted under the Loader and do not crossfade old and new assets.
- Do NOT animate all media mounts; historical and viewport-remounted media must remain immediate.
- Do NOT delay authoritative state changes, media requests, layout, or user interaction.
- Do NOT alter `StableMediaPreview`, cache keys, AssetVersion identity, node status, or API behavior.
- Do NOT animate transform, blur, scale, dimensions, or card chrome.

## Verification

- **Mechanical**: `npm run test -- CanvasMediaPreview.test.tsx AgentCanvasNode.test.tsx CanvasVideoPreview.test.tsx`; `npm run typecheck`; focused ESLint; `npm run build`.
- **Feel check**: complete one image generation and one video generation. The Loader must disappear, blank media must never flash, and the loaded result must fade from `0` to `1` over exactly `160ms` without showing the old asset beneath it.
- **Remount check**: pan a ready media node outside the React Flow render viewport and back. It must appear immediately from cache, with no replayed fade or blank frame.
- **Reduced motion**: the new result appears at full opacity as soon as it loads, with no animation.
- **Done when**: only a live `working → ready` generation transition fades, and every previously loaded/remounted card remains immediate.
