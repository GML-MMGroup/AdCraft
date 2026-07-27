## 2026-07-27: Publication checkpoint

### Failing evidence before implementation

```text
uv run pytest tests/test_v2_execution_result_publication.py::test_workflow_v2_service_initializes_execution_result_publication -q
1 failed: AttributeError: 'WorkflowV2Service' object has no attribute '_execution_result_publication'
```

### Focused verification

```text
uv run pytest tests/test_v2_execution_result_publication.py -q
6 passed
```

The remaining scheduler, provider-recovery, Pi isolation, parity, and final
acceptance tasks are intentionally still open.

## 2026-07-27: Scheduler and context checkpoint

### Regression evidence before the final-composition interface repair

```text
tests/test_v2_parallel_scheduler.py::test_v2_core_visual_to_video_flow_keeps_same_shot_selected_cells
failed after 48.718s: execution status was partial_failed.
final_video error: load_or_create_and_reconcile() got an unexpected keyword
argument workflow_override.
```

### Focused verification

```text
uv run pytest tests/test_v2_parallel_scheduler.py -q
18 passed in 179.19s

uv run pytest tests/test_v2_execution_result_publication.py \
  tests/test_v2_provider_result_commit_recovery.py \
  tests/test_v2_pi_agent_context.py -q
37 passed in 24.80s
```

These tests use deterministic fakes and isolated SQLite roots. Sentinel,
integration/media, full-suite, and real-provider acceptance remain open.

## 2026-07-27: Context isolation and parity checkpoint

```text
uv run pytest tests/test_v2_pi_agent_context.py tests/test_v2_pi_cutover_parity.py -q
28 passed in 3.95s
```

The initial context test failed for all four expert context kinds because
`data:image/png;base64,...` was accepted. The shared typed-context validator
now rejects `data:` and `;base64,` text before the runtime boundary.
