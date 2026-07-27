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
