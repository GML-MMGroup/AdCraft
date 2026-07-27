## 1. Reproduce And Bound The Regression

- [x] 1.1 In a dedicated monorepo backend worktree, add a focused failing test
  that constructs `WorkflowV2Service` and proves the missing
  `_execution_result_publication` collaborator.
- [x] 1.2 Add a focused failing scheduler test reproducing provider success
  followed by null selected IDs, blocked matching multi-view, and duplicate
  main generation on the next fill-missing run.
- [ ] 1.3 Preserve diagnostic evidence from
  `adwf_v2_bdb9a906250b` without adding a production recovery path or modifying
  its persisted data.
- [ ] 1.4 Compare only production-reachable Pi/V2 dependencies between the
  standalone backend and `apps/api`; classify each absent file as required,
  intentionally replaced, or unrelated.

## 2. Restore Execution-Result Publication

- [x] 2.1 Inspect the canonical
  `app/services/v2_execution_result_publication.py`,
  `app/services/workflow_v2.py`, authoring runtime, execution service, asset
  store, and runtime event service.
- [x] 2.2 Restore the publication service module and all required imports in
  the deployed `apps/api` package without overwriting unrelated newer code.
- [x] 2.3 Initialize `_execution_result_publication` in
  `WorkflowV2Service.__init__`.
- [x] 2.4 Restore call ordering for `uses_pending_publication`,
  `record_pending_selection`, `apply_pending_selections`, and
  `publish_terminal`.
- [x] 2.5 Preserve optimistic authoring-version checks, deferred publication,
  selected-relation idempotency, and SQLite authoring source-of-truth behavior.

## 3. Enforce Monotonic State And Fill-Missing Semantics

- [x] 3.1 Add/update focused tests in
  `tests/test_v2_execution_result_publication.py` proving pending selection,
  terminal publication, repeated publication, and concurrent-authoring
  deferral.
- [x] 3.2 Add/update scheduler tests proving a stale failure/queued snapshot
  cannot erase a successfully published selected version.
- [x] 3.3 Prove a valid selected main image is skipped by a later
  `fill_missing_required_slots` run.
- [x] 3.4 Prove one main-image success unlocks only its matching multi-view
  slot and supplies the matching selected reference version.
- [x] 3.5 Prove provider/publication infrastructure errors remain distinct from
  actual provider-generation errors and preserve durable output for recovery.

## 4. Re-Prove Pi Context Isolation

- [x] 4.1 Inspect `app/schemas/agent_operation_contexts.py`,
  `app/services/v2_pi_agent_context.py`, the Pi Sidecar operation registry,
  expert prompt registry, and current isolation tests.
- [x] 4.2 Restore any migration-omitted typed context schema, builder, registry,
  or direct dependency; do not add arbitrary dictionary or full-workflow
  compatibility fallbacks.
- [x] 4.3 Add Product, Character, Scene, BGM, targeted revision, Storyboard, and
  Video Director sentinel tests proving sibling full prompts do not cross
  contexts.
- [x] 4.4 Add parallel expert invocation coverage proving distinct invocation
  identities and no shared mutable context.
- [x] 4.5 Assert media bytes, base64/data URLs, credentials, absolute paths,
  unknown fields, complete workflow documents, and sibling full prompts are
  rejected before Pi/provider calls.

## 5. Migration Parity Gate

- [x] 5.1 Add a bounded production dependency/parity test that catches a
  referenced-but-absent module or referenced-but-uninitialized collaborator in
  the Pi/V2 execution roots.
- [x] 5.2 Restore the focused publication, scheduler, context-isolation, and
  cutover tests that were omitted from the deployed backend package.
- [ ] 5.3 Update the existing Pi equivalence matrix and append a dated
  correction to
  `openspec/changes/verify-pi-cutover-equivalence/verification.md`; retain the
  prior record for audit history.
- [ ] 5.4 Verify no Agno path, V1 fallback, frontend change, provider redesign,
  or Prompt-content rewrite was introduced.

## 6. Deterministic Verification

- [x] 6.1 Run the exact new failing tests before implementation and record the
  expected failure reason.
- [x] 6.2 Run the publication and scheduler files:
  `uv run pytest tests/test_v2_execution_result_publication.py
  tests/test_v2_provider_result_commit_recovery.py
  tests/test_v2_parallel_scheduler.py -q`.
- [x] 6.3 Run the Pi context and expert-isolation files, including the newly
  added sentinel and parallel-invocation tests.
- [ ] 6.4 Run a deterministic fake-provider critical path from main images
  through multi-views, storyboard media, and Final Composition.
- [ ] 6.5 Run `uv run pytest -m "integration or media" -q` only after focused
  suites pass.
- [ ] 6.6 Run the full backend suite once at final merge readiness; diagnose
  failures without skip, xfail, deletion, or weakened assertions.
- [ ] 6.7 Run `uv run ruff format .`, `uv run ruff check .`,
  `openspec validate repair-pi-cutover-publication-and-context-isolation
  --type change --strict`, and `git diff --check`.

## 7. Real Acceptance And Completion

- [ ] 7.1 Audit canonical runtime state and wait until no workflow execution is
  active before merging into the live `main` worktree.
- [ ] 7.2 Merge the verified task branch, restart the backend/Pi supervisor
  once, and verify compatible health.
- [ ] 7.3 Create one new workflow and run it through main images, matching
  multi-views, storyboard cells, shot videos, and Final Composition with real
  configured providers.
- [ ] 7.4 Inspect actual media and provider audit metadata; prove multi-view
  slots referenced the matching selected main versions and did not repeat the
  main-image request.
- [ ] 7.5 Verify canonical media URLs through the active frontend proxy without
  changing frontend code.
- [ ] 7.6 Write `verification.md` with commits, test commands/results, real
  workflow ID, asset/reference evidence, known external provider limitations,
  and confirmation that historical workflow data was not repaired.
