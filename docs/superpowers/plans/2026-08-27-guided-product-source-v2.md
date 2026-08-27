# Guided Product Source V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the frontend-only guided Product source flow for ordered existing and uploaded image AssetVersions.

**Architecture:** Deepen the existing `ProductSourceDecisionDock` with a pure ordered-selection model and a compact Project Asset picker. Preserve upload and submit identities, keep all Canvas data backend-authoritative, and route errors through the existing Decision Dock recovery model.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, Playwright, existing Agent Canvas API/hooks.

**Spec:** `docs/superpowers/specs/2026-08-27-guided-product-source-v2-design.md`

## Global Constraints

- Modify frontend files only; the canonical backend is read-only.
- Do not add APIs, client-created Nodes/Bindings, prose inference, or provider calls.
- Main requires one source; Multiview requires two through eight unique ordered sources.
- Preserve exact immutable identities and stable idempotency keys.
- Preserve working Editing, Asset Browser, Retry, and SSE behavior.

---

### Task 1: Ordered Product Source Draft Model

**Files:**
- Create: `apps/web/src/features/agent-canvas/chat/productSourceSelection.ts`
- Create: `apps/web/src/features/agent-canvas/chat/productSourceSelection.test.ts`

**Interfaces:**
- Produces: `ProductSourceDraftItem`, `addProductSourceItem`, `removeProductSourceItem`, `moveProductSourceItem`, `validateProductSourceDraft`, and `resolveProductSourceAssetVersions`.

- [ ] **Step 1: Write failing tests** for Main replacement, Multiview append, duplicate rejection, 2-8 validation, movement bounds, and mixed-source ordered resolution.
- [ ] **Step 2: Run** `npm test -- src/features/agent-canvas/chat/productSourceSelection.test.ts` and verify missing exports fail.
- [ ] **Step 3: Implement the pure immutable model** with no React or API dependencies.
- [ ] **Step 4: Re-run the test** and require all cases to pass.
- [ ] **Step 5: Commit** `test/feat(web): model ordered Product sources`.

### Task 2: Existing Project Asset Selection UI

**Files:**
- Create: `apps/web/src/features/agent-canvas/chat/ProductSourceAssetPicker.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/ProductSourceDecisionDock.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/agent-canvas-chat.css`
- Test: `apps/web/src/features/agent-canvas/chat/ProductSourceDecisionDock.test.tsx`

**Interfaces:**
- Consumes: `useAgentCanvasAssets({ scope: "project", mediaType: "image" })` and Task 1 draft operations.
- Produces: an accessible Project Assets list and ordered selected-source strip.

- [ ] **Step 1: Add failing component tests** for Ready existing AssetVersion selection, unavailable/versionless filtering, Main replacement, Multiview ordering, remove, and reorder.
- [ ] **Step 2: Run the focused Dock test** and verify the new expectations fail.
- [ ] **Step 3: Implement the compact picker and ordered strip** while preserving the Decision Dock frame and localized prompt.
- [ ] **Step 4: Re-run the focused Dock tests** and require them to pass.
- [ ] **Step 5: Commit** `feat(web): select ordered Product AssetVersions`.

### Task 3: Upload Receipt And Single-Confirmation Submission

**Files:**
- Modify: `apps/web/src/features/agent-canvas/chat/ProductSourceDecisionDock.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/ProductSourceDecisionDock.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/assets/useAgentCanvasAssets.test.tsx`

**Interfaces:**
- Consumes: `uploadFilesWithReceipts(files, options, idempotencyKeys)`.
- Produces: one typed `product_source` request with exact ordered references and optional exact handoff.

- [ ] **Step 1: Add failing tests** for mixed existing/upload order, stable upload keys across retry, pending handoff propagation, conflicting handoff rejection, Generate empty authority, and rapid double-click deduplication.
- [ ] **Step 2: Run the Dock and asset-hook tests** and verify the new cases fail.
- [ ] **Step 3: Resolve local entries sequentially at confirmation** and guard the whole transaction with a synchronous ref.
- [ ] **Step 4: Re-run focused tests** and require one confirmation to call submit once.
- [ ] **Step 5: Commit** `feat(web): preserve Product upload authority`.

### Task 4: Stale Recovery And Product Errors

**Files:**
- Modify: `apps/web/src/features/agent-canvas/chat/decisionDockIssue.ts`
- Modify: `apps/web/src/features/agent-canvas/chat/GuidedInteractionCard.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts`
- Test: `apps/web/src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx`
- Test: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx`

**Interfaces:**
- Produces: `productSourceDecisionDockIssueFromError` and stable Product question component identity.

- [ ] **Step 1: Add failing tests** for count, unreadable asset, compilation, and stale issues; prove stale refresh preserves the Product draft and uses new revisions.
- [ ] **Step 2: Run the focused tests** and verify Product-specific expectations fail.
- [ ] **Step 3: Implement bounded error projection and stable question identity** without automatic retry or Guidance Advance.
- [ ] **Step 4: Re-run the focused tests** and require all recovery cases to pass.
- [ ] **Step 5: Commit** `fix(web): recover guided Product source decisions`.

### Task 5: Refresh, Source-Only, And Runtime Regression

**Files:**
- Modify: `apps/web/src/features/agent-canvas/chat/ProductSourceDecisionDock.tsx`
- Test: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx`
- Test: `apps/web/src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.test.tsx`
- Test: `apps/web/src/features/agent-canvas/runtime/runtimeEventPolicy.test.ts`

**Interfaces:**
- Confirms existing Timeline/Workflow/Runtime refresh and adds Project Asset refresh after acceptance.

- [ ] **Step 1: Add failing regression tests** for accepted asset refresh, product_source wait suppressing Advance, SSE terminal refresh, and Ready source-only Product controls remaining hidden.
- [ ] **Step 2: Run the focused tests** and verify only missing behavior fails.
- [ ] **Step 3: Add the minimal refresh integration** without changing backend graph or existing source-only rendering rules.
- [ ] **Step 4: Re-run all Product-focused tests** and require them to pass.
- [ ] **Step 5: Commit** `test(web): cover Product source authority lifecycle`.

### Task 6: Browser Acceptance And Final Verification

**Files:**
- Create: `apps/web/tests/browser/agent-canvas-product-source-mock.html`
- Create: `apps/web/tests/browser/agent-canvas-product-source-mock.tsx`
- Create: `apps/web/tests/browser/agent-canvas-product-source-mock.spec.ts`
- Modify: `docs/contracts/2026-08-27-frontend-v2-contract-alignment-matrix.md`

**Interfaces:**
- Produces: browser evidence for Main, ordered Multiview, Generate, no duplicate submit, and source-only controls.

- [ ] **Step 1: Add the Mock-media browser harness** with intercepted upload, submit, Timeline, Workflow, Assets, Runtime, and SSE responses.
- [ ] **Step 2: Run the Playwright spec** and verify it fails before wiring all expected behavior.
- [ ] **Step 3: Complete the harness and matrix evidence** without invoking a provider.
- [ ] **Step 4: Run focused Vitest, `npm run typecheck`, `npm run build`, and the Product Playwright spec.**
- [ ] **Step 5: Record canonical backend commit and `/health` response**, then smoke fresh Product Main and Multiview workflows only when available; stop before real generation.
- [ ] **Step 6: Commit** `test(web): accept guided Product source flow`.
