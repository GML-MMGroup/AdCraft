# Project Cover Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Project page restore and display versioned cover previews quickly without repeating per-card metadata work or clearing already-visible covers.

**Architecture:** Keep project and cover metadata in a parent-owned identity map so virtual card mount/unmount does not own request state. Use the existing project catalog and cover caches as stale-while-revalidate inputs, keep previous covers during refresh, and remove `coverPriority` from metadata-query identity. Use a dedicated preview URL when the backend provides one, while retaining the current AssetVersion content URL as a safe fallback until the backend contract is extended.

**Tech Stack:** React, TypeScript, Vite, Vitest, Testing Library, existing `settledQueryResource`, `requestQueue`, localStorage project caches, and `StableMediaPreview`.

## Global Constraints

- Modify only `/data/longwei.wu/AdCraft` and this isolated frontend worktree.
- Do not access, modify, format, generate, synchronize, or test `/data/wenwu.meng/adWorkflow`.
- Preserve all existing user changes; do not reset, clean, or overwrite unrelated files.
- Do not invent backend fields. A structured `project.cover.preview_url` contract is a follow-up dependency; frontend fallback behavior must continue to work without it.
- Do not store image binary data or Base64 in localStorage.
- Do not claim live backend integration without a browser test proving the complete transition against a real backend.

### Task 1: Decouple cover metadata requests from image priority

**Files:**
- Modify: `apps/web/src/pages/projects/ProjectList.tsx`
- Test: `apps/web/src/pages/projects/ProjectList.cover.test.tsx`

**Interfaces:**
- `useProjectCover(project, coverPriority)` continues returning `V2ProjectCover | null | undefined`.
- `coverPriority` remains an image loading hint passed to `ProjectCard`, but no longer invalidates the metadata request effect.

- [x] **Step 1: Add a regression test** asserting that changing only `coverPriority` does not issue a second assets request for the same project identity.
- [x] **Step 2: Run the focused test and confirm it fails with the current effect dependency list.**
- [x] **Step 3: Remove `coverPriority` from the metadata effect dependencies and keep it only in queue scheduling/image props.**
- [x] **Step 4: Run the cover test file and confirm all request-count assertions pass.**
- [x] **Step 5: Commit:** `fix(projects): keep cover metadata identity stable across priority changes`.

### Task 2: Preserve visible covers during stale-while-revalidate

**Files:**
- Modify: `apps/web/src/pages/projects/ProjectList.tsx`
- Test: `apps/web/src/pages/projects/ProjectList.cover.test.tsx`

**Interfaces:**
- A cached or previously resolved `V2ProjectCover` remains rendered while its background lookup is pending.
- A confirmed null cover may still render the empty state; an in-flight refresh must not overwrite a non-null cover with `null` or `undefined`.

- [x] **Step 1: Add a regression test** that rerenders the same project identity while a refresh is pending and asserts the previous image remains present.
- [x] **Step 2: Run the test and confirm the current state reset produces the blank state.**
- [x] **Step 3: Initialize the cover entry from the previous entry/cache and only replace it after a lookup settles.**
- [x] **Step 4: Run the focused cover/cache tests and confirm the old cover remains visible during refresh.**
- [x] **Step 5: Commit:** `fix(projects): retain cached covers during background refresh`.

### Task 3: Use a preview rendition for project cards when available

**Files:**
- Modify: `apps/web/src/projects/v2ProjectCover.ts`
- Modify: `apps/web/src/projects/projectCoverCache.ts`
- Modify: `apps/web/src/components/Cards.tsx`
- Test: `apps/web/src/projects/v2ProjectCover.test.ts`
- Test: `apps/web/src/projects/projectCoverCache.test.ts`

**Interfaces:**
- Extend the existing frontend cover model with an optional `previewPath` only when it is present in an already-returned asset payload; do not infer a new backend field.
- `ProjectCard` uses `previewPath ?? mediaPath` for display and keeps `mediaPath` as the original AssetVersion content fallback.

- [x] **Step 1: Add fixtures with an existing `preview_url` and tests asserting it is retained/versioned for display.**
- [x] **Step 2: Run the focused cover tests and confirm the current model drops the preview URL.**
- [x] **Step 3: Thread the existing preview URL through cover resolution and localStorage normalization without changing generation identity.**
- [x] **Step 4: Update `ProjectPreviewImage` to use the preview path for the card while preserving the original path for full media use.**
- [x] **Step 5: Run cover/card tests and commit:** `perf(projects): prefer versioned preview renditions for cards`.

### Task 4: Add performance evidence and verify the complete frontend path

**Files:**
- Modify: `apps/web/src/pages/projects/ProjectList.cover.test.tsx`
- Create: `apps/web/tests/browser/project-cover-cache-mock.spec.ts`

**Interfaces:**
- The browser test uses mocked frontend-owned API routes only and records assets/content requests, cache reuse, and visible cover timing state.
- The test must not contact the canonical backend repository or claim live integration.

- [x] **Step 1: Add a deterministic browser fixture for first load, hard reload-equivalent remount, and virtual-window scroll.**
- [x] **Step 2: Assert one metadata request per mounted identity, no duplicate request from priority changes, and no provider/workflow request when asset data is sufficient.**
- [x] **Step 3: Assert cached cover metadata remains visible before the background request resolves.**
- [x] **Step 4: Run focused Vitest, browser mock tests, typecheck, and production build.**
- [x] **Step 5: Commit:** `test(projects): cover cache and virtual list regression coverage`.

## Backend Follow-up (not implemented in this plan)

The frontend can use an existing asset `preview_url`, but eliminating the default per-project `/assets` request requires a confirmed backend project-list contract containing `asset_id`, `version_id`, and preview rendition data. Until that contract is available, the frontend keeps the current fallback lookup and reports the N+1 path as partially optimized rather than removed.
