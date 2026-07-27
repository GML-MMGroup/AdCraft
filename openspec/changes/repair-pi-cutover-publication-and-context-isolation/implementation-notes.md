## 2026-07-27: Publication checkpoint

- Confirmed the deployed `apps/api` service called
  `_execution_result_publication` without importing, constructing, or shipping
  its implementation.
- Restored `V2ExecutionResultPublicationService` and its direct repository
  dependency `get_execution_result_revision()`.
- Restored execution-owned publication fields in `_initial_execution_state()`:
  `authoring_base_state_version`, `authoring_base_revision_no`, and
  `pending_selections`.
- Restored the focused publication regression tests and isolated SQLite test
  fixtures from the standalone backend. No provider call is made by these tests.

## 2026-07-27: Scheduler and final-composition checkpoint

- Restored the execution-owned pending-selection overlay at provider-task
  reconciliation and prevented per-slot semantic commits while an execution
  owns pending publication.
- Restored recovery and dynamic-slot guards so terminal publication remains
  the only authoring commit for execution-owned selections.
- Restored the final-composition timeline `workflow_override` contract used by
  the generation pipeline. The override is intentionally not persisted as an
  authoring mutation.
- Restored the focused scheduler, provider-result recovery, and Pi context
  tests omitted from the deployed package.

## 2026-07-27: Context isolation and parity checkpoint

- Added a bounded parity test for every deployment dependency restored by this
  change: publication collaborator, repository idempotency query, execution
  overlay fields, and Final Composition timeline override.
- Added isolated expert context tests for Product, Character, Scene, and BGM
  ownership, unsafe field rejection, and parallel invocation identity.
- Tightened the shared typed-context validator to reject data URLs and base64
  payloads before a Pi sidecar or provider can receive them.

## 2026-07-27: Verification and scope audit

- Read-only inspection of `adwf_v2_bdb9a906250b` retained the diagnostic
  evidence: failed main-image runtime entries already carried canonical asset
  and version IDs while their matching multi-view slots were blocked with null
  selections. No persisted workflow, runtime, asset, or provider-task file was
  modified.
- The standalone-to-deployed audit classified the publication service, public
  authoring lookup, execution overlay fields, and timeline override as required
  production dependencies. The remaining compared Pi/V2 collaborators were
  already present or intentionally owned by the deployed package.
- Scope audit found no Agno path, V1 fallback, frontend change, provider
  redesign, or prompt-content rewrite. The only `frontend` match is a test name
  describing polling behavior.
- The earlier Pi equivalence record received a dated additive correction; its
  historical evidence remains intact.
