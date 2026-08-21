# Agent Canvas Runtime And Drag Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Agent Canvas refresh amplification and guarantee safe drag cleanup without changing backend contracts.

**Architecture:** Add small pure helpers for runtime refresh identity and drag-session reconciliation, then consume them from the existing runtime and page hooks. Add workflow-scoped pointer caches inside the existing chat hook so repeated timeline reads reuse immutable resources.

**Tech Stack:** React 19, TypeScript, React Flow 12, Vitest, Testing Library, Playwright.

## Global Constraints

- Modify frontend files under `apps/web` only.
- Keep the existing Agent Canvas runtime, session, and chat stores.
- Do not change backend API paths or response contracts.
- Preserve immediate terminal-state updates and retry failed hydration requests.

---

### Task 1: Runtime Refresh Deduplication

**Files:**
- Create: `apps/web/src/features/agent-canvas/runtime/runtimeRefreshIdentity.ts`
- Create: `apps/web/src/features/agent-canvas/runtime/runtimeRefreshIdentity.test.ts`
- Modify: `apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.ts`
- Modify: `apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.test.tsx`

**Interfaces:**
- Produces: `runtimeRefreshIdentity(event)` and `sameRuntimePresentation(left, right)`.
- Consumes: normalized `CanvasRuntimeEventV2` and `CanvasRuntimeSnapshotV2` values.

- [ ] Write tests proving duplicate waiting/started events share one identity while progress and terminal events remain distinct.
- [ ] Run the focused tests and confirm they fail because the helper is absent.
- [ ] Implement the pure identity and runtime presentation comparison helpers.
- [ ] Add a hook test proving duplicate runtime events issue one refresh and timestamp-only responses retain the runtime state reference.
- [ ] Run runtime tests and confirm they pass.

### Task 2: Drag Session Recovery And Structural Sharing

**Files:**
- Modify: `apps/web/src/features/agent-canvas/canvas/draggingNodeState.ts`
- Modify: `apps/web/src/features/agent-canvas/canvas/draggingNodeState.test.ts`
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPage.tsx`
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts`

**Interfaces:**
- Produces: `beginNodeDrag(...)`, `cancelNodeDrag(...)`, and reference-preserving reconciliation.
- Consumes: the latest presented snapshot, React Flow nodes, and the active drag identifier set.

- [ ] Write failing tests for stale identifier replacement, pointer cancellation, and unchanged-node reference reuse.
- [ ] Run the drag tests and verify the expected failures.
- [ ] Implement the drag helpers and structural sharing.
- [ ] Wire `pointercancel`, blur, visibility change, unmount cleanup, and layout failure refresh into `AgentCanvasPage`.
- [ ] Run drag and page source tests and confirm they pass.

### Task 3: Workflow-Scoped Chat Pointer Cache

**Files:**
- Modify: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts`
- Modify: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx`

**Interfaces:**
- Produces: workflow-scoped cached hydration for proposal, decision bundle, and capability turn pointers.
- Consumes: existing timeline pages and live chat events.

- [ ] Write a failing hook test that refreshes the same timeline twice and expects one proposal, one decision-bundle, and one completed-turn request.
- [ ] Run the focused chat test and verify the repeated calls fail the assertion.
- [ ] Implement promise-aware immutable pointer caches and completed-turn hydration tracking.
- [ ] Clear all hydration caches on workflow changes and avoid caching failures.
- [ ] Run the chat tests and confirm they pass.

### Task 4: Verification And Browser Stress Test

**Files:**
- Modify only if a discovered regression requires a scoped correction.

- [ ] Run all focused Agent Canvas runtime, drag, page, chat, session, and layout tests.
- [ ] Run `npm run typecheck`.
- [ ] Run `npm run lint`.
- [ ] Run `npm run build`.
- [ ] Run a Playwright drag stress test against `adwf_v2_e90fd91e37c280af`, without modifying backend layout, and inspect console errors, visible node count, and long tasks.
- [ ] Review the final diff for frontend-only scope and commit the branch.
