# Agent Chat Stage Threads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compress Agent Canvas execution logs into readable, authoritative stage threads while preserving all existing user interactions and recovery behavior.

**Architecture:** A pure projection module converts normalized timeline items into display units keyed by backend identifiers. Dedicated Stage Thread components render collapsed historical summaries and expanded active/error details; the panel remains an orchestrator and the current Guided Interaction remains pinned above the composer.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, CSS.

**Spec:** `docs/superpowers/specs/2026-08-27-agent-chat-stage-threads-design.md`

## Global Constraints

- Do not add or call backend APIs.
- Do not infer workflow state from message text, canvas nodes, node positions, or bindings.
- Do not alter Guided Interaction, Retry, Guidance Advance, or SSE behavior.
- Preserve failed receipts and retry controls.
- Keep the UI monochrome.

---

### Task 1: Preserve Timeline Provenance

**Files:**
- Modify: `apps/web/src/types-v2.ts`
- Modify: `apps/web/src/features/agent-canvas/model/normalizers.ts`
- Test: `apps/web/src/features/agent-canvas/model/normalizers.test.ts`

**Interfaces:**
- Produces: `ChatMessageV2.message_kind`, `capability_id`, and preserved planning `proposal_id`.

- [ ] Write a failing normalizer test asserting that a `planning_progress` entry becomes a message with `message_kind: "planning_progress"` and typed relation IDs.
- [ ] Run the focused test and confirm it fails because provenance is missing.
- [ ] Extend `ChatMessageV2` and the raw timeline adapter with the minimal fields.
- [ ] Run the focused test and existing timeline normalizer tests.

### Task 2: Build The Pure Stage Thread Projection

**Files:**
- Create: `apps/web/src/features/agent-canvas/chat/stageThreadProjection.ts`
- Create: `apps/web/src/features/agent-canvas/chat/stageThreadProjection.test.ts`

**Interfaces:**
- Consumes: `ChatTimelineItemV2[]`.
- Produces: `buildStageThreadTimeline(items): StageTimelineUnit[]`.

- [ ] Write failing tests for capability grouping, selected proposal summaries, Script Writer aggregation, latest-document deduplication, and retained failed receipts.
- [ ] Run the focused projection test and confirm expected failures.
- [ ] Implement stable-ID grouping and chronological unit ordering.
- [ ] Run the projection tests and refactor only after green.

### Task 3: Render Stage Threads

**Files:**
- Create: `apps/web/src/features/agent-canvas/chat/StageThread.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx`

**Interfaces:**
- Consumes: `StageThreadUnit` and existing activity retry/revise handlers.
- Produces: collapsed completed summaries and expanded active/error histories.

- [ ] Write failing component tests for completed collapse, selected option display, expansion, Script Writer revision count, and visible failed recovery content.
- [ ] Run the focused component tests and confirm failures.
- [ ] Implement `StageThread` using existing `CapabilityActivityRow`, `ProposalCard`, and `ActionReceiptCard` for expanded details.
- [ ] Replace the direct timeline map with projected-unit rendering while preserving current interaction placement.
- [ ] Run focused component tests.

### Task 4: Compact Guidance Progress And Styles

**Files:**
- Modify: `apps/web/src/features/agent-canvas/chat/GuidanceSessionProgress.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/agent-canvas-chat.css`
- Modify: `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx`

**Interfaces:**
- Consumes: authoritative `GuidedSessionStateV2.journey`.
- Produces: compact current-stage and three-group progress summary.

- [ ] Write a failing test that expects compact progress and rejects the old metadata labels.
- [ ] Run the focused test and confirm it fails on the old card.
- [ ] Implement the compact summary and monochrome thread styling, including reduced-motion behavior.
- [ ] Run focused tests.

### Task 5: Verification And Integration

**Files:**
- Review all files changed above.

- [ ] Run `npm test -- src/features/agent-canvas/chat/stageThreadProjection.test.ts src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx src/features/agent-canvas/model/normalizers.test.ts`.
- [ ] Run `npm run typecheck`.
- [ ] Run `npm run build`.
- [ ] Inspect the focused diff for unrelated changes.
- [ ] Commit the feature branch and merge it into local `main` with `git merge --no-ff feat/agent-chat-stage-threads`.
