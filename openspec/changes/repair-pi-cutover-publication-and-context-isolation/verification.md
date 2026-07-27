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
parallel-context, parity-gate, integration/media, full-suite, and real-provider
acceptance remain open.
