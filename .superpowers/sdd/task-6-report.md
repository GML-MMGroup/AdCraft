# Task 6 Report: Decompose V2 Slot Application Operations

## Final Status

PASS with one unrelated verification concern documented below.

- Base: `3e808c75d5348e62b66fcf20f5b424cd78758557`
- Implementation baseline: `9cd294aaecc699095f1f68d5b8575d7eadb85ad6`
- Final result: the commit containing this report; resolve with `git rev-parse HEAD`
- Commit message: `refactor(web): split v2 slot operation services`
- Branch: `refactor/frontend-hardening-task6`
- Remote Git: not accessed

## RED/GREEN Evidence

### Characterization

The initial facade characterization suite was written before production
extraction. After correcting one invalid fixture target, all 7 tests passed
against the original 1,131-line hook. The suite recorded:

- prompt flush request/order, dirty cleanup, error propagation, and loading
  cleanup;
- reference deduplication and attach-before-regenerate ordering;
- prompt-before-regenerate behavior and workflow/assets/snapshot/version
  refresh ordering;
- selected versus working version identity and BGM selection notification;
- storyboard confirmation and description regeneration ordering;
- free-node create/generate/absorb/delete payloads and media target guards.

### RED

1. `slotMutationRunner.test.ts` initially failed to resolve
   `slotMutationRunner.ts`, proving the shared service did not exist.
2. The runner lifecycle test then failed because error status was published
   before in-flight cleanup for slot submissions.
3. A reference-registration characterization failed because submission state
   was raised after the draft attachment and failed attachments were not yet
   characterized.
4. Provider polling characterization failed because status moved after
   refresh/snapshot and a stale workflow error was reported.

### GREEN

- Shared runner tests: 4/4 passed.
- Focused Slot operation tests: 30/30 passed across 3 files.
- Real HTTP 412 and 428 tests verified `If-Match`, conflict-store state, latest
  workflow refresh, no silent retry, and `{ ok: false }` facade behavior.
- Added error coverage verifies failed reference attachments, cleanup-before-
  status for Slot submissions, provider status-before-refresh ordering, and
  stale-workflow error suppression.

## Architecture

`useV2SlotOperations` remains the caller-facing facade with the same 32 action
keys, argument shapes, and return behavior. It now assembles narrow typed ports
for:

- `slotMutationRunner`: workflow identity/revision guards, reconciliation,
  stale mutation errors, ordered workflow/assets/snapshot/version refresh,
  status/error propagation, and in-flight cleanup;
- `slotPromptOperations`: item/slot prompts, editor actions, and dirty draft
  flushing;
- `slotReferenceOperations`: local reference drafts, upload/registration,
  attach/remove, artifact merging, and reference cleanup;
- `slotGenerationOperations`: regenerate, item run, provider polling, working
  and selected version operations, and version loading;
- `storyboardOperations`: summary confirmation and description regeneration;
- `freeNodeOperations`: create, generate, absorb, and delete.

The two existing final-timeline pass-through actions remain in the facade with
their original guarded try/catch flow. No final-composition module or
backend/runtime contract was changed.

## Changed Files

- `apps/web/src/features/workflow/v2/slots/useV2SlotOperations.ts`
- `apps/web/src/features/workflow/v2/slots/operations/slotMutationRunner.ts`
- `apps/web/src/features/workflow/v2/slots/operations/slotPromptOperations.ts`
- `apps/web/src/features/workflow/v2/slots/operations/slotReferenceOperations.ts`
- `apps/web/src/features/workflow/v2/slots/operations/slotGenerationOperations.ts`
- `apps/web/src/features/workflow/v2/slots/operations/storyboardOperations.ts`
- `apps/web/src/features/workflow/v2/slots/operations/freeNodeOperations.ts`
- `apps/web/src/features/workflow/v2/slots/operations/slotMutationRunner.test.ts`
- `apps/web/src/features/workflow/v2/slots/useV2SlotOperations.characterization.test.tsx`
- `apps/web/src/features/workflow/v2/slots/useV2SlotOperations.test.tsx`
- `.superpowers/sdd/task-6-report.md`

## Verification

- `npm test -- --run <all Slot/V2 tests>`: 16 files, 103 tests passed.
- `npm test`: 26 files, 163 tests passed.
- `npm run typecheck`: passed.
- `npm run lint`: passed.
- Explicit ESLint run over all new operation/test files: passed.
- `npm run build`: passed; 461 modules transformed.
- `git diff --check`: passed before the final commit.

An extra `npm run perf:bundle` check failed without any budget/test change:

- core JS: 1313 KiB, budget 1281 KiB;
- untouched final-composition editor chunk: 97 KiB, budget 96 KiB;
- untouched core CSS: 197 KiB, budget 180 KiB.

The Task 6 build changed the generated WorkflowPage chunk by approximately
0.3 KiB between local builds; the reported budget gaps are materially larger
and include untouched CSS/final-composition outputs. Budgets were not weakened.

## LOC and Complexity

Final metrics use `wc -l` and ESLint's `complexity` rule:

- Facade LOC: 1,131 before, 398 after (733 lines removed, 64.8% reduction).
- Current facade plus six services and runner: 2,335 LOC.
- Facade maximum cyclomatic complexity: 28 before, 6 after.
- Maximum cyclomatic complexity across the owned production surface: 28
  before, 14 after.

Aggregate LOC increased because typed service contracts, grouped adapters, and
independently callable operations are now explicit. The former complexity-28
draft-reference routine was split into upload, library-registration, and
attachment helpers without changing call order.

## Self-Review

- Public action names/order are locked by a facade-surface test.
- Prompt persistence remains before reference attachment/regeneration.
- No automatic retry, conflict discard, or backend payload change was added.
- Reconciliation still uses the existing workflow application revision guard.
- Workflow, asset/runtime refresh, snapshot, version load, status, and draft
  cleanup ordering are locked by tests.
- Selected and working version identities remain separate.
- Storyboard media refresh and free-node target guards are preserved.
- Operation factories receive grouped read-model/state/reference/version ports,
  not the original hook argument bag.
- The out-of-scope final-composition actions were restored to their original
  facade flow, and an accidental facade type re-export was removed.
- No backend, page assembly, runtime transport, final-composition, asset, CSS,
  or remote Git file was modified.

## Concerns

- `slotReferenceOperations.ts` remains the largest service at 849 LOC. Its
  highest-complexity draft resolution path was split into focused helpers.
- `apps/web/node_modules` was already untracked in the worktree and remains
  untouched.
- The optional bundle-budget command is red for the unrelated limits listed
  above; required tests, typecheck, lint, and production build are green.
