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
