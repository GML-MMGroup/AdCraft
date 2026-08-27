# Frontend V2 Contract Alignment Implementation Plan

## 1. Contract Baseline

- Add the full contract matrix and design record.
- Add failing strict-normalizer tests for Product interactions, upload handoffs, immutable binding versions, Character projection fields, and missing SSE events.

## 2. Public Types and Normalizers

- Extend Product upload response and Guided Interaction unions.
- Add Product source content/action/submission types.
- Add `source_asset_version_id` to image binding reads and require it for writes.
- Add canonical Character projection fields.
- Add Product/import SSE event names and refresh policy.

## 3. Product Upload and Decision Dock

- Preserve full upload receipts and stable upload idempotency.
- Implement Product source Dock using existing Guided Interaction Submit.
- Keep 202 submissions pending until authoritative close/failure.
- Refresh stale authority while preserving the local draft.

## 4. Immutable Binding Writes

- Propagate project asset version IDs through asset-browser identities.
- Validate new image binding references at the mutation boundary.
- Update binding fixtures and focused tests.

## 5. Source-Only Execution Guards

- Centralize the source-only predicate.
- Apply it to UI, single Run, Global Run, and migration selection.
- Add Product and Video source-only regression tests.

## 6. Character Cardinality

- Add a pure 0/1/N Character occurrence projection and compact UI.
- Render only persisted Journey occurrence data.
- Add zero, one, and multiple occurrence tests.

## 7. Editing Integration Evidence

- Add import-to-canvas SSE refresh.
- Preserve existing Editing implementation.
- Add Playwright Mock-media acceptance covering export, download, import, preview, downstream binding, native audio, and no Provider Task creation.

## 8. Verification

- Run targeted Vitest files.
- Run `npm run typecheck`.
- Run `npm run build`.
- Run only the new Mock-media Playwright suite.
- Review the diff and contract matrix statuses.
- Confirm backend worktree remains untouched.
- Stop and report before any real-provider acceptance.
