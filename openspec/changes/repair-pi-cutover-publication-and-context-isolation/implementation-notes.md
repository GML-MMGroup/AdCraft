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
