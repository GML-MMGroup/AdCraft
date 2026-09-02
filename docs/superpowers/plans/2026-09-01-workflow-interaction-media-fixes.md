# Workflow Interaction and Media Preview Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Make the Workflow canvas easier to pan and drag, keep SVG edges crisp at all zoom levels, and restore lazy first-frame previews for video assets that lack a backend poster rendition.

**Architecture:** Retain React Flow's viewport transform, RAF-batched controlled node movement, and frozen-edge overlay. Reduce paint cost by simplifying edge styles and preserving interaction-time effect suspension. Introduce a focused lazy video preview component that uses server posters when available and only loads source metadata for visible poster-less videos.

**Tech Stack:** React, TypeScript, XYFlow/React Flow, Vitest, Testing Library, CSS, Playwright browser validation.

## Global Constraints

- Modify only `/data/longwei.wu/AdCraft` and this isolated worktree; do not modify backend or downstream mirrors.
- Preserve all existing frontend behavior and uncommitted changes in the main worktree.
- All edges must remain visible while dragging; no viewport virtualization or edge hiding is introduced.
- Do not change frontend/backend API contracts.
- Use the exact versioned `mediaAssetContentPath(asset)` URL for native video fallback.
- Keep source media loading lazy and bounded to nodes near the viewport.
- Poster-less native video source activation is FIFO and limited to one active source load at a time.

---

### Task 1: Add failing regression tests for edge clarity and lazy video fallback

**Files:**
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx`

**Interfaces:**
- Tests assert CSS and rendered DOM contracts that the implementation must satisfy.

- [ ] **Step 1: Add the edge-style regression assertions**

Extend the existing edge test to require `vector-effect: non-scaling-stroke`, an opaque-enough base stroke, and no base or selected drop-shadow filter. Keep existing assertions for selected animation and interaction-time pause.

- [ ] **Step 2: Add the poster-less video behavior tests**

Add a test asset with `preview_url`, `poster_url`, `thumbnail_url`, and `preview_path` all null and a versioned `media_url`. Mock `IntersectionObserver` with a controllable callback. Assert the video initially has `preload="none"` and no `src`; after the observer callback it has the versioned content URL and `preload="metadata"`. Keep the existing backend-poster test asserting an image is rendered and no native video is mounted.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
cd /data/longwei.wu/AdCraft-worktrees/workflow-interaction-media-fixes-20260901/apps/web
npx vitest run src/features/agent-canvas/AgentCanvasPage.chrome.test.ts src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx
```

Expected: the new edge assertions fail because the current CSS still uses a scaling 58% stroke and drop shadows; the poster-less video test fails because the current implementation renders only a placeholder.

### Task 2: Restore a lazy native-video first-frame fallback

**Files:**
- Create: `apps/web/src/features/agent-canvas/canvas/CanvasVideoPreview.tsx`
- Create: `apps/web/src/features/agent-canvas/canvas/canvasVideoPreviewScheduler.ts`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.css`

**Interfaces:**
- `CanvasVideoPreview({ asset, label, onMediaDimensionsResolved })` renders a poster image when a derived rendition exists and a lazy native video fallback otherwise.
- It uses `useAgentCanvasVideoPoster(asset, videoRef)` and `requestNativeVideoFirstFrame(video)` with `mediaAssetContentPath(asset)`.

- [ ] **Step 1: Implement the lazy preview component and FIFO source scheduler**

Create a component that observes its video element with `rootMargin: "240px"`, initially renders `preload="none"` without a source, and marks the node eligible on intersection (or immediately when IntersectionObserver is unavailable). Pass eligible nodes through `acquireCanvasVideoPreviewLoad()`, a FIFO scheduler that resolves one release callback at a time; release on loaded data, error, unmount, or an 8-second timeout. Use `useAgentCanvasVideoPoster` for the generated poster URL. Once the scheduler grants a slot, set `src={mediaAssetContentPath(asset)}`, `preload="metadata"`, and call `requestNativeVideoFirstFrame` from `onLoadedMetadata`. Render a `StableMediaPreview` image when a derived rendition exists; otherwise render the native video with the generated poster if one becomes available. Preserve dimension callbacks and `aria-label`.

- [ ] **Step 2: Replace the poster-less placeholder branch**

In `MediaSurface`, replace the `!mediaUrl` video placeholder with `CanvasVideoPreview`; retain the existing image and backend-poster paths. Keep the play button callback and event propagation behavior unchanged.

- [ ] **Step 3: Add only interaction-safe video CSS**

Ensure the fallback video fills the stage, uses `object-fit: cover`, and remains `pointer-events: none`. Do not add animations or filters to the video surface.

- [ ] **Step 4: Run the focused node tests and verify GREEN**

Run the focused Vitest command from Task 1. Expected: all node tests pass, including lazy activation and backend-poster behavior.

### Task 3: Make edges crisp and cheaper to paint during pan and drag

**Files:**
- Modify: `apps/web/src/features/agent-canvas/agent-canvas-page.css`
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts`

**Interfaces:**
- CSS applies equally to live React Flow edges and the existing frozen SVG edge snapshots.

- [ ] **Step 1: Update base edge paint**

Change the base edge rule to:

```css
vector-effect: non-scaling-stroke;
stroke: rgb(229 231 238 / 86%);
stroke-width: 1.2;
filter: none;
```

Keep rounded caps/joins and transitions. Remove selected/related drop shadows while retaining their white stroke, width, dash pattern, and animation. Keep the existing `.is-interacting` filter/transition/animation pause rules so all edges stay rendered while the browser performs less filter work.

- [ ] **Step 2: Verify CSS tests pass**

Run:

```bash
cd /data/longwei.wu/AdCraft-worktrees/workflow-interaction-media-fixes-20260901/apps/web
npx vitest run src/features/agent-canvas/AgentCanvasPage.chrome.test.ts
```

Expected: edge assertions pass and existing frozen-edge/interaction assertions remain green.

### Task 4: Run complete frontend verification and browser validation

**Files:**
- No additional source files; record evidence in the final handoff.

**Interfaces:**
- Browser checks use the historical project route `/workflow/proj_1ce0210d9406de73` and backend-backed data already available in the local environment.

- [ ] **Step 1: Run frontend typecheck, focused tests, build, and diff checks**

Run:

```bash
cd /data/longwei.wu/AdCraft-worktrees/workflow-interaction-media-fixes-20260901/apps/web
npm run typecheck
npx vitest run src/features/agent-canvas/AgentCanvasPage.chrome.test.ts src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx
npm run build
git diff --check
```

- [ ] **Step 2: Start the isolated frontend**

Start the Vite dev server on port 5192 with the existing backend base URL. Do not alter or restart the main worktree server.

- [ ] **Step 3: Verify the historical workflow in a browser**

Navigate to `/workflow/proj_1ce0210d9406de73`. Confirm the canvas renders its nodes and all edges. Zoom to the minimum and inspect a base edge's computed `vectorEffect`, `strokeWidth`, `stroke`, and `filter`. Pan the canvas and drag a node; count edge elements before and after and confirm none disappear. Observe a poster-less video node: it initially has no source request, then loads its versioned content URL when near the viewport and displays either a generated poster or native first frame.

- [ ] **Step 4: Re-measure interaction performance**

Capture frame intervals during a 1-second pan and node drag, plus edge path mutation counts. Compare with the recorded baseline and report actual numbers; do not claim a fixed FPS unless measured.

- [ ] **Step 5: Commit the isolated change**

```bash
cd /data/longwei.wu/AdCraft-worktrees/workflow-interaction-media-fixes-20260901
git add -f docs/superpowers/specs/2026-09-01-workflow-interaction-media-fixes-design.md docs/superpowers/plans/2026-09-01-workflow-interaction-media-fixes.md
git add apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx apps/web/src/features/agent-canvas/canvas/CanvasVideoPreview.tsx apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.css apps/web/src/features/agent-canvas/agent-canvas-page.css
git commit -m "fix(web): restore video previews and crisp canvas edges"
```
