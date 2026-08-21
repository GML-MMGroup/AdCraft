# Agent Canvas Drag Snapshot Coordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent runtime workflow snapshots from corrupting controlled React Flow node state during single-node or multi-node dragging.

**Architecture:** Keep backend and session workflow updates live while a page-level drag transaction defers only React Flow node replacement. Put deterministic filtering and rebuilding in `draggingNodeState.ts`, then sequence refs and React state in `AgentCanvasPage.tsx`.

**Tech Stack:** React 19, TypeScript, React Flow, Vitest

## Global Constraints

- Modify frontend files only.
- Do not block SSE ingestion or backend layout persistence.
- Rebuild from the complete latest snapshot after drag stop.
- Persist only finite `x` and `y` values.

---

### Task 1: Pure Drag Snapshot Coordination

**Files:**
- Modify: `apps/web/src/features/agent-canvas/canvas/draggingNodeState.ts`
- Test: `apps/web/src/features/agent-canvas/canvas/draggingNodeState.test.ts`

**Interfaces:**
- Consumes: canonical React Flow nodes, current React Flow nodes, active dragged IDs, and final drag-stop nodes.
- Produces: `deferNodeSnapshotDuringDrag`, `finishNodeDrag`, and finite layout positions for page integration.

- [ ] **Step 1: Write failing tests for a deferred SSE snapshot, complete multi-drag cleanup, full snapshot restoration, and non-finite coordinates.**

- [ ] **Step 2: Run `npm test -- --run src/features/agent-canvas/canvas/draggingNodeState.test.ts` and confirm the new assertions fail because the coordination functions do not exist.**

- [ ] **Step 3: Implement pure helpers that never mutate node arrays, retain the latest complete snapshot, clear the full active ID set, overlay finite final coordinates, preserve selection, and remove `dragging`.**

- [ ] **Step 4: Re-run the focused test and confirm all drag-state assertions pass.**

### Task 2: Agent Canvas Event Integration

**Files:**
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPage.tsx`
- Test: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts`

**Interfaces:**
- Consumes: Task 1 pure coordination helpers.
- Produces: drag-aware React Flow snapshot application and finite-only position persistence.

- [ ] **Step 1: Add failing source-integration assertions for pending snapshot refs, deferred `setNodes`, complete drag cleanup, and finite persistence.**

- [ ] **Step 2: Run `npm test -- --run src/features/agent-canvas/AgentCanvasPage.chrome.test.ts` and confirm the new assertions fail against the current handlers.**

- [ ] **Step 3: Add latest/pending snapshot refs, defer the synchronization effect during active drag, and rebuild nodes synchronously in `onNodeDragStop` before calling `updateNodePositions`.**

- [ ] **Step 4: Run both focused test files and confirm they pass.**

### Task 3: Verification

**Files:**
- Verify only; no production files added.

**Interfaces:**
- Consumes: completed implementation.
- Produces: evidence that the fix compiles, passes regressions, and builds.

- [ ] **Step 1: Run the focused drag, layout, and Agent Canvas chrome tests.**

- [ ] **Step 2: Run `npm run typecheck` and ESLint on changed frontend files.**

- [ ] **Step 3: Run `npm run build` and `git diff --check`.**

- [ ] **Step 4: Review the final diff for backend changes, unrelated refactors, and missing test coverage.**
