## Background

The Pi cutover passed its historical verification gate, but a real V2 workflow
run in the monorepo backend disproved production equivalence.

The migrated `WorkflowV2Service` calls
`V2ExecutionResultPublicationService.uses_pending_publication()`,
`record_pending_selection()`, and `publish_terminal()`, while the deployed
backend package omits the service module, import, and constructor wiring. A
provider can therefore generate and register a valid main image before the
scheduler fails with an uninitialized-service error. The slot loses its
canonical selected version, downstream multi-view slots remain blocked, and a
later Global Run generates another independent main image.

The migration must also preserve the existing engineering boundary that each
Pi expert receives a bounded, typed, owner-specific context. Full sibling
prompts, complete workflow documents, media bytes, and unrelated Agent history
must never be concatenated into another expert or provider prompt.

## Problem

- Production packaging did not preserve a required V2 result-publication
  service and its focused tests.
- The completed Pi equivalence gate did not detect a production symbol that was
  referenced but absent or not initialized.
- Provider success can be followed by scheduler failure, leaving valid media as
  an unselected working result and blocking all selected-version dependencies.
- Fill-missing reruns can regenerate already successful main slots, causing
  duplicate assets and visible identity/style drift.
- Existing Prompt isolation requirements need migration-level evidence, not
  only prompt instructions or fake Pi protocol coverage.

## Goals

- Restore the canonical V2 execution-result publication implementation and
  constructor wiring in the deployed backend package.
- Preserve exactly-once terminal publication, selected-version relations, and
  monotonic successful slot state.
- Ensure Global Run skips valid selected slots and unlocks matching multi-view
  and downstream slots after publication.
- Add a bounded migration parity audit for production-reachable Pi/V2
  dependencies and focused tests.
- Re-prove typed, owner-specific Pi context isolation with sibling sentinel
  tests and parallel invocation coverage.
- Validate one new workflow through main images, multi-views, storyboard media,
  and Final Composition after deterministic tests pass.

## Non-goals

- No recovery or mutation of historical workflow
  `adwf_v2_bdb9a906250b`.
- No public frontend contract or UI change.
- No Prompt-content quality rewrite.
- No provider selection, retry, or failover redesign.
- No wholesale copy of every file that differs between the standalone backend
  and the monorepo backend.
- No restoration of Agno or V1 workflow behavior.

## API/Interface Impact

No public HTTP API change.

The following existing endpoints consume the corrected behavior:

- `POST /api/v2/workflows/{workflow_id}/run`
- `GET /api/v2/workflows/{workflow_id}`
- `GET /api/v2/workflows/{workflow_id}/assets`
- `GET /api/v2/workflows/{workflow_id}/runtime`
- `GET /api/v2/workflows/{workflow_id}/events`
- `GET /api/v2/workflows/{workflow_id}/events/stream`
- `POST /api/v2/workflows/plan-from-chat`
- `POST /api/v2/workflows/{workflow_id}/chat-actions`

Internal interfaces restored or verified:

- `V2ExecutionResultPublicationService`
- `WorkflowV2Service` publication-service initialization and call ordering
- `V2AgentContextBuilder`
- typed Agent operation contexts in `agent_operation_contexts.py`
- the Pi Sidecar operation boundary consuming those typed contexts

## Data Contract Impact

No new public schema is introduced.

The repair preserves existing execution metadata:

- `authoring_base_state_version`
- `pending_selections`
- `execution_result_revision_status`
- `execution_result_revision_no`

SQLite remains the V2 authoring source of truth. Workflow JSON remains a
rebuildable operational projection. Existing canonical asset versions and
`selected_for_slot` relations remain the downstream dependency contract.

## Error/Event Impact

- A normal provider success must no longer end as
  `v2_execution_internal_error` because a publication collaborator is absent.
- Existing `slot_selected_version_updated` events remain canonical and are
  emitted only after selected state is readable.
- Existing deferred-publication behavior remains
  `execution_result_revision_deferred` when authoring advances during a run.
- No new frontend-required event name is added.
- Internal construction/parity failures fail tests and startup verification;
  they are not converted into user-visible media-generation failures.

## Tests

- Focused publication-service tests for pending selections, terminal
  publication, idempotency, and concurrent-authoring deferral.
- A `WorkflowV2Service` construction test proving every production-referenced
  collaborator exists and is initialized.
- Scheduler tests proving provider success becomes selected, downstream
  multi-view slots unlock, and fill-missing reruns skip valid selected slots.
- Stale-state tests proving failed or queued snapshots cannot overwrite a
  published successful selection.
- Pi context sentinel tests proving sibling full prompts and unrelated history
  do not enter another expert context or provider prompt.
- A deterministic fake-provider V2 critical-path test.
- One controlled real-provider workflow acceptance run after merge readiness.

## Rollout/Compatibility

The change is backward-compatible for public V2 clients and requires no
frontend modification. It applies to newly created workflows and new
executions only; no historical data repair path is added.

Implementation must occur in a dedicated worktree and branch. Merge into the
live `main` worktree only when no workflow execution is active. Restart the
backend/Pi stack once, then create a new workflow for real acceptance.

