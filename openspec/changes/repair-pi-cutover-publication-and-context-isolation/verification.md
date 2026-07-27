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

## 2026-07-27: Final deterministic gate

### Historical diagnostic preservation

Read-only inspection of the live persisted instance
`adwf_v2_bdb9a906250b` found two failed executions where failed main-image
runtime entries retained canonical asset/version IDs while the corresponding
multi-view slots remained blocked without selected IDs. This change did not
modify any file under that workflow's persisted data.

### Production dependency and scope audit

- Required and restored: `V2ExecutionResultPublicationService`, public
  `WorkflowAuthoringRepository.get_execution_result_revision`, execution
  overlay initialization, and the final-composition `workflow_override`
  compatibility contract.
- Already present or intentionally deployed: the remaining compared Pi context,
  sidecar, prompt, scheduler, asset, and runtime collaborators.
- No Agno path, V1 fallback, frontend change, provider redesign, or prompt
  rewrite was introduced.
- The dated correction was appended to
  `verify-pi-cutover-equivalence/verification.md` without rewriting its prior
  audit record.

### Deterministic critical path and marker coverage

```text
uv run pytest tests/test_v2_parallel_scheduler.py -q
18 passed in 179.19s
```

`test_v2_core_visual_to_video_flow_keeps_same_shot_selected_cells` exercised
main images through matching multi-views, storyboard cells, shot videos, and
Final Composition using deterministic fakes. A collection audit showed that
the deployed `integration or media` selection contains exactly these same 18
scheduler tests, so the completed containing-file run is the non-duplicative
verification of that marker scope.

### Full suite and static checks

```text
uv run pytest -q --durations=50 --junitxml=/tmp/pi-cutover-full-suite.xml
82 passed in 217.44s

uv run ruff format apps/api/app apps/api/tests
3 files reformatted

uv run ruff check apps/api/app apps/api/tests
All checks passed

openspec validate repair-pi-cutover-publication-and-context-isolation --type change --strict
Change 'repair-pi-cutover-publication-and-context-isolation' is valid

git diff --check
passed
```

No deterministic test failures remain.

## 2026-07-27: Merge and live-acceptance status

The verified branch was merged into the AdCraft deployment branch
`chore/monorepo-migration` with merge commit `3ab179c` after the canonical
active-execution audit reported:

```json
{"active_execution_count": 0, "active_executions": [], "quiescent": true}
```

The merged API/Pi supervisor could not be restarted for real-provider
acceptance. The native deployment script correctly rejects this host's FFmpeg
`4.3`; it requires a version in the range `>=6.1,<8`. The existing service on
port 8000 has a process working directory of `/data/wenwu.meng/adWorkflow`, so
it is the standalone backend rather than this merged AdCraft monorepo. No
service from the other repository was restarted or modified. Tasks 7.2 through
7.6 remain open pending a deployable AdCraft runtime with the required FFmpeg
capabilities.
