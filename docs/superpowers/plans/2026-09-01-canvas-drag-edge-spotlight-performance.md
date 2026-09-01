# Canvas Drag Edge and Spotlight Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep every canvas edge visible while reducing drag-time SVG path recalculation and pointer spotlight style recalculation.

**Architecture:** During node drag, React Flow renders only edges connected to the dragged node set. All other edges remain visible through a static SVG snapshot captured before the first position update. The pointer spotlight controller is suspended for the duration of any canvas interaction and resumes on the next real pointer movement.

**Tech Stack:** React, TypeScript, XYFlow/React Flow, SVG, Vitest, browser tests.

## Global Constraints

- Modify only the frontend repository `/data/longwei.wu/AdCraft`.
- Do not change backend, downstream mirrors, API contracts, media loading, or `onlyRenderVisibleElements`.
- Preserve the canonical `edges` state; drag-time filtering is a render projection only.
- All edges must remain visually present during node drag.
- Existing drag cancellation, multi-selection, edge selection, connection creation, and single layout PATCH behavior must remain intact.

---

### Task 1: Add a pure drag-edge projection and snapshot model

**Files:**
- Create: `apps/web/src/features/agent-canvas/canvas/frozenCanvasEdges.ts`
- Test: `apps/web/src/features/agent-canvas/canvas/frozenCanvasEdges.test.ts`

**Interfaces:**
- `edgeIdsConnectedToNodes(edges, draggedNodeIds): Set<string>` returns live edge IDs.
- `partitionCanvasEdges(edges, draggedNodeIds): { liveEdges; frozenEdges }` preserves original order and object identity.
- `FrozenCanvasEdgeSnapshot` stores the captured edge group SVG markup needed by the frozen overlay.

- [ ] **Step 1: Write failing tests** for single-node and multi-node partitioning, empty drag sets, stable ordering, and identity preservation.
- [ ] **Step 2: Run** `npm --prefix apps/web exec vitest run src/features/agent-canvas/canvas/frozenCanvasEdges.test.ts` and confirm the new module is missing.
- [ ] **Step 3: Implement** the pure helpers without reading DOM or mutating source edges.
- [ ] **Step 4: Add snapshot extraction helpers** that read the current edge SVG once and return serializable edge-group markup containing path, marker, class, and style data; if extraction is unavailable, return an empty snapshot and let the caller retain full live edges.
- [ ] **Step 5: Run the focused test** and confirm it passes.

### Task 2: Suspend pointer spotlight during interaction

**Files:**
- Modify: `apps/web/src/features/agent-canvas/canvas/canvasPointerSpotlight.ts`
- Modify: `apps/web/src/features/agent-canvas/canvas/canvasPointerSpotlight.test.ts`
- Modify: `apps/web/src/features/agent-canvas/agent-canvas-page.css`

**Interfaces:**
- Extend `CanvasPointerSpotlightController` with `suspend()` and `resume()`.
- `suspend()` cancels pending RAF work, clears active state, and ignores movement without calling `getBoundingClientRect()` or writing CSS variables.
- `resume()` only permits future pointer events; it does not redraw stale coordinates.

- [ ] **Step 1: Add failing tests** proving suspension cancels a pending frame, movement while suspended performs no reads/writes, and resume waits for a fresh movement.
- [ ] **Step 2: Run** the focused spotlight test and confirm failure.
- [ ] **Step 3: Implement** the suspended flag and controller methods; keep leave/dispose safe and idempotent.
- [ ] **Step 4: Add CSS fallback** for `.agent-canvas-board.is-interacting .agent-canvas-pointer-background` to disable opacity, mask, and transition while JavaScript is suspended.
- [ ] **Step 5: Run** the focused spotlight tests and existing pointer background tests.

### Task 3: Integrate frozen edges and spotlight lifecycle into the canvas surface

**Files:**
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPageSurface.tsx`
- Modify: `apps/web/src/features/agent-canvas/agent-canvas-page.css`
- Test: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts`

**Interfaces:**
- Add a local drag projection state containing `draggedNodeIds` and frozen snapshots.
- Add a `FrozenEdgesOverlay` rendered inside the React Flow viewport with `pointer-events: none`.

- [ ] **Step 1: Add integration tests** for drag start/stop, multi-node drag, pointer cancellation, and window blur; assert full edge visibility is restored and spotlight is resumed.
- [ ] **Step 2: Run the focused browser/component tests** and confirm the lifecycle assertions fail.
- [ ] **Step 3: On `onNodeDragStart`, capture the current edge SVG before position changes, partition edges, suspend spotlight, and store the drag session.
- [ ] **Step 4: Pass only live connected edges to React Flow while dragging, and render frozen non-connected edges through the overlay in the same viewport coordinate space. If no valid snapshot exists, pass all canonical edges so edges never disappear.
- [ ] **Step 5: On drag stop/cancel/blur/pointercancel, clear the projection, restore canonical edges, resume spotlight, and preserve the existing final-position reconciliation and single PATCH.
- [ ] **Step 6: Keep viewport pan/zoom behavior unchanged except for spotlight suspension.
- [ ] **Step 7: Run the focused integration tests.**

### Task 4: Coalesce drag position changes and verify performance

**Files:**
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPageSurface.tsx`
- Test: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts`

- [ ] **Step 1: Add a test harness** that dispatches sustained position changes and asserts at most one controlled node update per animation frame while non-position changes remain immediate.
- [ ] **Step 2: Implement an RAF queue** for `position` changes with `dragging: true`; flush before drag stop and cancellation.
- [ ] **Step 3: Run focused tests** for drag reconciliation, cancellation, and layout persistence.
- [ ] **Step 4: Run the browser performance scenario** using the 27-node/50-edge workflow. Verify all edge paths remain visible, non-connected live paths do not mutate during drag, spotlight CSS writes and bounds reads are zero, and only one layout PATCH occurs.
- [ ] **Step 5: Run frontend typecheck and the focused Agent Canvas test set.**

### Task 5: Commit the isolated performance change

- [ ] **Step 1: Review** `git diff` and confirm no backend or unrelated frontend files changed.
- [ ] **Step 2: Commit** with `git add` restricted to the files above and message `perf(web): reduce canvas drag edge and spotlight work`.
- [ ] **Step 3: Report** focused test results and browser measurements, including any edge-type limitations.
