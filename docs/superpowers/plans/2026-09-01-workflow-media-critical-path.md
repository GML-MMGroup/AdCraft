# Workflow Media Critical Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce the historical Workflow page's critical-path latency and interaction cost without hiding nodes or edges and without changing Workflow business contracts.

**Architecture:** Keep the React Flow graph fully mounted and preserve the existing frozen-edge drag projection. Make the initial data path deterministic by removing redundant authority refreshes, then defer only heavy node media hydration so Timeline and Creative Session are not competing with full-resolution media. Keep all changes behind existing frontend components and API methods.

**Tech Stack:** React 18, TypeScript, XYFlow/React Flow, Vitest, existing V2 API client, CSS media loading primitives.

## Global Constraints

- Work only in the frontend repository `/data/longwei.wu/AdCraft` and this isolated worktree.
- Do not modify, format, generate, synchronize, or test `/data/wenwu.meng/adWorkflow` or downstream mirrors.
- Preserve all nodes and all edges during drag, viewport movement, and media deferral.
- Do not introduce a backend endpoint or change V2 contracts.
- Do not cap the number of concurrently generating nodes.
- Use versioned media URLs and preserve existing Blob/cache behavior.
- Run frontend-owned focused tests, typecheck, and build only.

---

### Task 1: Prevent redundant initial Workflow refresh

**Files:**
- Modify: `apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.ts`
- Test: `apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.test.tsx`

**Interfaces:**
- `replayEvents` returns whether it applied any events.
- The initial SSE `onopen` authority refresh runs only when replay changed the runtime boundary.

- [x] **Step 1: Write the failing test**

Add a test covering an idle initial runtime connection where the replay contains no events; assert that the baseline runtime is fetched once and Workflow is not refreshed solely by `onopen`.

- [x] **Step 2: Run the focused test and verify it fails**

Run: `npm run test -- --run apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.test.tsx`

Expected: the new assertion fails because the current `onopen` callback always calls `refreshWorkflow()` for the initial connection.

- [x] **Step 3: Implement the minimal change**

Change `replayEvents` to return a boolean that becomes true when at least one event is processed. In the initial `onopen` sync, call `refreshWorkflow()` and increment `chatRevision` only when replay reported an event or the cursor advanced.

- [x] **Step 4: Run the focused test and verify it passes**

Run the same command. Expected: all runtime hook tests pass.

- [x] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.ts apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.test.tsx
git commit -m "perf(web): avoid redundant initial workflow refresh"
```

### Task 2: Defer heavy node media hydration

**Files:**
- Modify: `apps/web/src/workflow/StableMediaPreview.tsx`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx`
- Test: `apps/web/src/workflow/StableMediaPreview.test.tsx`
- Test: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx`

**Interfaces:**
- `StableMediaPreview` accepts an optional `deferMs?: number` that delays cache/network hydration while preserving the canonical versioned URL and existing lazy IntersectionObserver behavior.
- Canvas node image and video poster previews use a short delay only; audio remains `preload="none"`.

- [x] **Step 1: Write the failing test**

Add a test using fake timers that renders `StableMediaPreview` with `deferMs={200}`, verifies the image has no source before 200ms, then verifies hydration starts after the delay. Add a node render assertion that canvas media passes the deferred preview behavior.

- [x] **Step 2: Run the focused tests and verify they fail**

Run: `npm run test -- --run apps/web/src/workflow/StableMediaPreview.test.tsx apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx`

Expected: the new deferred-loading assertion fails because `StableMediaPreview` has no `deferMs` behavior.

- [x] **Step 3: Implement the minimal change**

Add the optional delay inside the existing effect. Cancel the timer on cleanup, do not alter `src`, cache keys, or version query parameters, and keep the current IntersectionObserver path after the delay. Pass `deferMs={200}` to node image and poster previews only.

- [x] **Step 4: Run the focused tests and verify they pass**

Run the same command. Expected: all existing media and node tests pass.

- [x] **Step 5: Commit**

```bash
git add apps/web/src/workflow/StableMediaPreview.tsx apps/web/src/workflow/StableMediaPreview.test.tsx apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx
git commit -m "perf(web): defer heavy canvas media hydration"
```

### Task 3: Verify graph visibility and interaction behavior

**Files:**
- Modify only if a measured regression is found: `apps/web/src/features/agent-canvas/AgentCanvasPageSurface.tsx`
- Test: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts`
- Test: `apps/web/src/features/agent-canvas/canvas/frozenCanvasEdges.test.ts`

**Interfaces:**
- Existing `onlyRenderVisibleElements={false}` remains unchanged.
- Existing `FrozenCanvasEdgesOverlay` remains the source of truth for unrelated edges during drag.

- [x] **Step 1: Add regression assertions**

Assert that the Workflow surface keeps `onlyRenderVisibleElements={false}`, creates a frozen edge projection on drag start, and renders the frozen overlay while preserving live edges connected to the dragged node.

- [x] **Step 2: Run focused graph tests**

Run: `npm run test -- --run apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts apps/web/src/features/agent-canvas/canvas/frozenCanvasEdges.test.ts`

Expected: all assertions pass with every edge still represented.

- [x] **Step 3: Commit**

```bash
git add apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts apps/web/src/features/agent-canvas/canvas/frozenCanvasEdges.test.ts
git commit -m "test(web): protect workflow edge visibility during drag"
```

### Task 4: Frontend verification and browser re-measurement

**Files:**
- No source changes unless a focused test exposes a regression.
- Evidence: `docs/superpowers/plans/2026-09-01-workflow-media-critical-path.md` and final report.

- [x] **Step 1: Run frontend checks**

Run from `apps/web`:

```bash
npm run typecheck
npm run test -- --run apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.test.tsx apps/web/src/workflow/StableMediaPreview.test.tsx apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts
npm run build
```

- [x] **Step 2: Run browser validation against the historical project**

Using Playwright, open `http://127.0.0.1:5189/workflow/proj_1ce0210d9406de73` and record:

- duplicate Workflow and Agent Settings requests;
- time until Timeline request starts;
- image/video request counts and transferred bytes;
- drag frame interval and edge visibility;
- node, edge, Blob, and heap counts after route cycles.

- [x] **Step 3: Compare against the recorded baseline**

Baseline to compare: 26 nodes, 50 edges, FCP ~1.15s, LCP ~1.45s, ~9.85MB decoded fetch content, duplicate Workflow/Agent Settings calls, and drag mean frame interval ~32.7ms with P95 50ms.

- [x] **Step 4: Commit verification-only adjustments if required**

Only commit a narrowly scoped correction if the browser test proves a regression. Otherwise leave source unchanged after the three implementation commits.
