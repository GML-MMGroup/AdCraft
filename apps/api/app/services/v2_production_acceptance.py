from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import (
    WorkflowV2,
    WorkflowV2PlanningClarificationResponse,
    WorkflowV2RunStartResponse,
    WorkflowV2RuntimeSnapshot,
)
from app.schemas.workflow_v2_acceptance import V2WorkflowAcceptanceFixture
from app.schemas.workflow_v2_production_acceptance import (
    V2ProductionAcceptanceFailure,
    V2ProductionAcceptanceFixture,
    V2ProductionAcceptanceReport,
    V2ProductionAcceptanceRunRequest,
    V2ProductionAcceptanceRunState,
    V2ProductionAcceptanceRunView,
)
from app.services.agent_trace import utc_now
from app.services.v2_execution_service import V2ExecutionService
from app.services.v2_input_assets import V2InputAssetService, asset_locator
from app.services.v2_production_acceptance_fixtures import (
    V2ProductionAcceptanceFixtureBundle,
    V2ProductionAcceptanceFixtureRegistry,
    V2ProductionAcceptanceFixtureRegistryError,
)
from app.services.v2_production_acceptance_preflight import V2ProductionAcceptancePreflight
from app.services.v2_production_acceptance_review import (
    V2ProductionAcceptanceReviewRenderer,
)
from app.services.v2_production_acceptance_store import (
    V2ProductionAcceptanceStore,
    V2ProductionAcceptanceStoreError,
    hash_idempotency_key,
)
from app.services.v2_production_acceptance_validator import (
    V2ProductionAcceptanceValidator,
)
from app.services.v2_provider_tasks import V2ProviderTaskStore
from app.services.v2_runtime_events import V2RuntimeEventService
from app.services.v2_workflow_acceptance import (
    V2WorkflowAcceptanceFixtureRegistry as DeterministicAcceptanceFixtureRegistry,
)
from app.services.v2_workflow_acceptance import V2WorkflowAcceptanceValidator
from app.services.v2_final_composition_renderer import V2MediaProbe
from app.services.workflow_v2 import WorkflowV2Error, WorkflowV2Service


TERMINAL_ACCEPTANCE_STATUSES = {"completed", "blocked", "failed", "cancelled"}
TERMINAL_EXECUTION_STATUSES = {"completed", "partial_failed", "failed", "cancelled"}
NONTERMINAL_PROVIDER_TASK_STATUSES = {"submitted", "waiting", "polling", "running"}


class V2ProductionAcceptanceServiceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        acceptance_run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.acceptance_run_id = acceptance_run_id


class _WorkflowService(Protocol):
    def plan_from_prompt(
        self, request: Any
    ) -> WorkflowV2 | WorkflowV2PlanningClarificationResponse: ...

    def run_workflow(
        self,
        workflow_id: str,
        *,
        wait: bool = False,
    ) -> WorkflowV2RunStartResponse: ...

    def get_workflow(self, workflow_id: str) -> WorkflowV2: ...

    def runtime_snapshot(self, workflow_id: str) -> WorkflowV2RuntimeSnapshot: ...


class V2ProductionAcceptancePlanningValidator:
    def __init__(self, validator: V2WorkflowAcceptanceValidator | None = None) -> None:
        self._validator = validator or V2WorkflowAcceptanceValidator()

    def validate(
        self,
        fixture: V2ProductionAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> list[V2ProductionAcceptanceFailure]:
        deterministic_fixture = V2WorkflowAcceptanceFixture(
            fixture_id=fixture.fixture_id,
            title=fixture.title,
            input_prompt=fixture.request.prompt,
            duration_seconds=fixture.request.duration_seconds,
            expected_counts=fixture.expected_counts,
            required_nodes=fixture.required_nodes,
            required_slot_types=fixture.required_slot_types,
            forbidden_terms_by_slot_type=(
                DeterministicAcceptanceFixtureRegistry()
                .get("iphone_14_pro_core")
                .forbidden_terms_by_slot_type
            ),
            required_reference_relationships=fixture.required_reference_relationships,
        )
        report = self._validator.validate_planning(
            fixture=deterministic_fixture,
            workflow=workflow,
        )
        stable_codes = {
            "acceptance_explicit_count_mismatch",
            "acceptance_missing_required_node",
            "acceptance_missing_required_item",
            "acceptance_missing_required_slot",
        }
        return [
            V2ProductionAcceptanceFailure(
                code=(
                    failure.code
                    if failure.code in stable_codes
                    else "acceptance_prompt_contract_failed"
                ),
                source_error_code=(None if failure.code in stable_codes else failure.code),
                stage=failure.stage,
                message=failure.message,
                node_id=failure.node_id,
                item_id=failure.item_id,
                slot_id=failure.slot_id,
            )
            for failure in report.failures
        ]


class V2ProductionAcceptanceService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        fixture_registry: V2ProductionAcceptanceFixtureRegistry | None = None,
        store: V2ProductionAcceptanceStore | None = None,
        preflight: Any | None = None,
        input_assets: V2InputAssetService | None = None,
        workflow_service: _WorkflowService | None = None,
        planning_validator: Any | None = None,
        terminal_validator: Any | None = None,
        execution_service: Any | None = None,
        provider_task_store: Any | None = None,
        runtime_events: Any | None = None,
        review_renderer: Any | None = None,
        background_submit: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._data_dir = self._settings.media_data_dir
        self._fixtures = fixture_registry or V2ProductionAcceptanceFixtureRegistry()
        self._store = store or V2ProductionAcceptanceStore(self._data_dir)
        self._preflight = preflight or V2ProductionAcceptancePreflight(settings=self._settings)
        self._input_assets = input_assets or V2InputAssetService(settings=self._settings)
        self._workflow_service = workflow_service or WorkflowV2Service(settings=self._settings)
        self._planning_validator = planning_validator or V2ProductionAcceptancePlanningValidator()
        self._terminal_validator = terminal_validator or V2ProductionAcceptanceValidator(
            data_dir=self._data_dir,
            media_probe=V2MediaProbe(ffprobe_path=_ffprobe_path(self._settings.ffmpeg_path)),
        )
        self._execution_service = execution_service or V2ExecutionService(self._data_dir)
        self._provider_tasks = provider_task_store or V2ProviderTaskStore(
            self._data_dir,
            poll_interval_seconds=self._settings.v2_provider_task_poll_interval_seconds,
            timeout_seconds=self._settings.v2_provider_task_timeout_seconds,
        )
        self._runtime_events = runtime_events or V2RuntimeEventService(self._data_dir)
        self._review_renderer = review_renderer or V2ProductionAcceptanceReviewRenderer(
            self._data_dir,
            store=self._store,
        )
        self._background_submit = background_submit or _start_background_thread
        self._live_orchestrations: set[str] = set()
        self._live_lock = threading.Lock()

    def start_run(
        self,
        request: V2ProductionAcceptanceRunRequest,
        idempotency_key: str,
    ) -> V2ProductionAcceptanceRunView:
        if not self._settings.v2_production_acceptance_enabled:
            raise V2ProductionAcceptanceServiceError(
                "production_acceptance_disabled",
                "Production acceptance starts are disabled.",
            )
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise V2ProductionAcceptanceServiceError(
                "production_acceptance_idempotency_key_required",
                "Idempotency-Key is required.",
            )
        bundle = self._load_fixture(request.fixture_id)
        self._reconcile_active_owner()
        try:
            state, replay = self._store.claim_run(
                request.fixture_id,
                hash_idempotency_key(normalized_key),
            )
        except V2ProductionAcceptanceStoreError as exc:
            raise _service_error_from_store(exc) from exc
        if replay:
            return self._view(self._reconcile(state), idempotent_replay=True)

        blockers = self._preflight.check(bundle)
        if blockers:
            blocked = self._store.update_run(
                state.acceptance_run_id,
                expected_revision=state.revision,
                lifecycle_status="blocked",
                technical_verdict="pending",
                current_stage="preflight",
                blockers=blockers,
                finished_at=utc_now().isoformat(),
            )
            self._store.release_active(blocked.acceptance_run_id)
            return self._view(blocked)

        queued = self._store.update_run(
            state.acceptance_run_id,
            expected_revision=state.revision,
            lifecycle_status="queued",
            technical_verdict="pending",
            current_stage="queued",
            started_at=utc_now().isoformat(),
        )
        with self._live_lock:
            self._live_orchestrations.add(queued.acceptance_run_id)
        try:
            self._background_submit(lambda: self._orchestrate(queued.acceptance_run_id, bundle))
        except Exception as exc:  # noqa: BLE001 - mapped to a stable acceptance failure.
            with self._live_lock:
                self._live_orchestrations.discard(queued.acceptance_run_id)
            failed = self._fail(
                queued.acceptance_run_id,
                "acceptance_execution_start_failed",
                "orchestration_start",
                exc,
            )
            return self._view(failed)
        return self._view(queued)

    def get_run(self, acceptance_run_id: str) -> V2ProductionAcceptanceRunView:
        state = self._load_run(acceptance_run_id)
        return self._view(self._reconcile(state))

    def get_report(self, acceptance_run_id: str) -> V2ProductionAcceptanceReport:
        state = self._reconcile(self._load_run(acceptance_run_id))
        report = self._load_report(acceptance_run_id)
        if report is not None:
            return report
        if (
            state.lifecycle_status not in TERMINAL_ACCEPTANCE_STATUSES
            or state.lifecycle_status == "blocked"
        ):
            raise V2ProductionAcceptanceServiceError(
                "production_acceptance_report_not_ready",
                "Production acceptance report is not ready.",
                acceptance_run_id=acceptance_run_id,
            )
        self._ensure_terminal_report(state)
        report = self._load_report(acceptance_run_id)
        if report is None:
            raise V2ProductionAcceptanceServiceError(
                "production_acceptance_report_failed",
                "Production acceptance report could not be generated.",
                acceptance_run_id=acceptance_run_id,
            )
        return report

    def _orchestrate(
        self,
        acceptance_run_id: str,
        bundle: V2ProductionAcceptanceFixtureBundle,
    ) -> None:
        try:
            self._heartbeat(acceptance_run_id, "fixture_ingestion", lifecycle_status="running")
            locators = []
            declarations = {asset.relative_path: asset for asset in bundle.fixture.input_assets}
            for relative_path, path in bundle.asset_paths.items():
                declaration = declarations[relative_path]
                record = self._input_assets.save_asset_bytes(
                    body=path.read_bytes(),
                    filename=path.name,
                    content_type=declaration.content_type,
                    semantic_type=declaration.intent,
                    display_name=declaration.display_name,
                    intent=declaration.intent,
                    metadata={
                        "origin": "production_acceptance_fixture",
                        "fixture_id": bundle.fixture.fixture_id,
                    },
                )
                locators.append(asset_locator(record.asset_id, record.version_id))

            self._heartbeat(acceptance_run_id, "planning")
            planning_request = bundle.fixture.request.model_copy(
                update={
                    "input_asset_locators": [
                        *bundle.fixture.request.input_asset_locators,
                        *locators,
                    ]
                },
                deep=True,
            )
            planned = self._workflow_service.plan_from_prompt(planning_request)
            if isinstance(planned, WorkflowV2PlanningClarificationResponse):
                self._fail(
                    acceptance_run_id,
                    "acceptance_planning_clarification_required",
                    "planning",
                    RuntimeError(planned.message),
                    source_error_code=planned.error_code,
                )
                return
            if not isinstance(planned, WorkflowV2):
                raise RuntimeError("Production planner returned an unsupported response.")

            state = self._load_run(acceptance_run_id)
            state = self._store.update_run(
                acceptance_run_id,
                expected_revision=state.revision,
                workflow_id=planned.workflow_id,
                current_stage="planning_validation",
            )
            planning_failures = self._planning_validator.validate(bundle.fixture, planned)
            if planning_failures:
                self._fail_with_failure(acceptance_run_id, planning_failures[0])
                return

            self._heartbeat(acceptance_run_id, "execution_start")
            started = self._workflow_service.run_workflow(planned.workflow_id, wait=False)
            state = self._load_run(acceptance_run_id)
            self._store.update_run(
                acceptance_run_id,
                expected_revision=state.revision,
                lifecycle_status="running",
                technical_verdict="pending",
                current_stage="execution_started",
                execution_id=started.execution_id,
            )
        except WorkflowV2Error as exc:
            self._fail(
                acceptance_run_id,
                "acceptance_workflow_planning_failed",
                "planning",
                exc,
                source_error_code=exc.code,
            )
        except Exception as exc:  # noqa: BLE001 - persisted through stable failure taxonomy.
            state = self._load_run(acceptance_run_id)
            code = (
                "acceptance_execution_start_failed"
                if state.current_stage == "execution_start"
                else "acceptance_workflow_planning_failed"
            )
            self._fail(acceptance_run_id, code, state.current_stage, exc)
        finally:
            with self._live_lock:
                self._live_orchestrations.discard(acceptance_run_id)

    def _reconcile_active_owner(self) -> None:
        try:
            active_run_id = self._store.active_run_id()
        except V2ProductionAcceptanceStoreError as exc:
            raise _service_error_from_store(exc) from exc
        if not active_run_id:
            return
        state = self._load_run(active_run_id)
        reconciled = self._reconcile(state)
        if reconciled.lifecycle_status in TERMINAL_ACCEPTANCE_STATUSES:
            self._store.release_active(active_run_id)

    def _reconcile(
        self,
        state: V2ProductionAcceptanceRunState,
    ) -> V2ProductionAcceptanceRunState:
        if state.lifecycle_status in TERMINAL_ACCEPTANCE_STATUSES:
            if state.lifecycle_status != "blocked":
                self._ensure_terminal_report(state)
            return self._load_run(state.acceptance_run_id)
        if not state.workflow_id:
            with self._live_lock:
                is_live = state.acceptance_run_id in self._live_orchestrations
            if not is_live and _is_stale(
                state.updated_at,
                self._settings.v2_stale_running_timeout_seconds,
            ):
                return self._fail(
                    state.acceptance_run_id,
                    "acceptance_orchestrator_interrupted",
                    state.current_stage,
                    RuntimeError(
                        "Acceptance orchestration was interrupted before workflow creation."
                    ),
                )
            return state
        if not state.execution_id:
            return state

        execution = self._execution_service.load_state(state.workflow_id, state.execution_id) or {}
        try:
            runtime = self._workflow_service.runtime_snapshot(state.workflow_id)
            runtime_status = runtime.execution_status
        except Exception:  # noqa: BLE001 - durable execution state remains authoritative.
            runtime_status = ""
        execution_status = str(execution.get("status") or runtime_status or "running")
        tasks = self._provider_tasks.list_tasks(state.workflow_id)
        task_statuses = {_value(task, "status") for task in tasks}
        if execution_status in TERMINAL_EXECUTION_STATUSES:
            return self._finish_from_execution(state, execution_status, execution)

        lifecycle_status = (
            "waiting"
            if task_statuses & NONTERMINAL_PROVIDER_TASK_STATUSES or execution_status == "waiting"
            else "running"
        )
        if (
            lifecycle_status != state.lifecycle_status
            or state.current_stage != "workflow_execution"
        ):
            state = self._store.update_run(
                state.acceptance_run_id,
                expected_revision=state.revision,
                lifecycle_status=lifecycle_status,
                technical_verdict="pending",
                current_stage="workflow_execution",
            )
        return state

    def _finish_from_execution(
        self,
        state: V2ProductionAcceptanceRunState,
        execution_status: str,
        execution_state: dict[str, Any],
    ) -> V2ProductionAcceptanceRunState:
        if execution_status == "completed":
            terminal = self._validate_terminal(state)
        else:
            code = (
                "acceptance_execution_partial_failed"
                if execution_status == "partial_failed"
                else "acceptance_execution_failed"
            )
            terminal = self._fail(
                state.acceptance_run_id,
                code,
                "execution",
                RuntimeError(
                    str(execution_state.get("error") or "").strip()
                    or f"Workflow execution ended with status {execution_status}."
                ),
                source_error_code=(
                    str(execution_state.get("error_code") or "").strip() or execution_status
                ),
                lifecycle_status="cancelled" if execution_status == "cancelled" else "failed",
            )
        self._store.release_active(state.acceptance_run_id)
        return terminal

    def _validate_terminal(
        self,
        state: V2ProductionAcceptanceRunState,
    ) -> V2ProductionAcceptanceRunState:
        if self._terminal_validator is None:
            failure = V2ProductionAcceptanceFailure(
                code="acceptance_execution_orphaned",
                stage="terminal_validation",
                message="Terminal validator is not configured.",
            )
            return self._fail_with_failure(state.acceptance_run_id, failure)
        workflow = self._workflow_service.get_workflow(str(state.workflow_id))
        runtime = self._workflow_service.runtime_snapshot(str(state.workflow_id))
        execution = (
            self._execution_service.load_state(str(state.workflow_id), str(state.execution_id))
            or {}
        )
        tasks = self._provider_tasks.list_tasks(str(state.workflow_id))
        events = self._runtime_events.load_events(str(state.workflow_id))
        report = self._terminal_validator.validate(
            acceptance_run_id=state.acceptance_run_id,
            fixture=self._load_fixture(state.fixture_id).fixture,
            workflow=workflow,
            execution_state=execution,
            runtime=runtime,
            provider_tasks=tasks,
            capability_snapshot=self._preflight.capability_snapshot(),
            events=events,
        )
        report_path, review_path = self._persist_report_artifacts(report)
        current = self._load_run(state.acceptance_run_id)
        return self._store.update_run(
            state.acceptance_run_id,
            expected_revision=current.revision,
            lifecycle_status=report.lifecycle_status,
            technical_verdict=report.technical_verdict,
            current_stage="terminal_validation",
            failure=report.failures[0] if report.failures else None,
            report_path=report_path,
            review_path=review_path,
            finished_at=utc_now().isoformat(),
        )

    def _ensure_terminal_report(self, state: V2ProductionAcceptanceRunState) -> None:
        report = self._load_report(state.acceptance_run_id)
        if report is None:
            if state.lifecycle_status == "blocked":
                return
            report = V2ProductionAcceptanceReport(
                acceptance_run_id=state.acceptance_run_id,
                fixture_id=state.fixture_id,
                workflow_id=state.workflow_id,
                execution_id=state.execution_id,
                lifecycle_status=state.lifecycle_status,
                technical_verdict=state.technical_verdict,
                manual_review_required=state.technical_verdict == "passed",
                fixture_snapshot=self._load_fixture(state.fixture_id).fixture.model_dump(
                    mode="json"
                ),
                capability_snapshot=self._preflight.capability_snapshot(),
                checks=[],
                failures=[state.failure] if state.failure else [],
                warnings=[],
                metrics={},
                provider_task_summaries=[],
                review_manifest=[],
                created_at=utc_now().isoformat(),
            )
            report_path, review_path = self._persist_report_artifacts(report)
        else:
            report_path = self._store.report_relative_path(state.acceptance_run_id)
            if self._store.review_exists(state.acceptance_run_id):
                review_path = self._store.review_relative_path(state.acceptance_run_id)
            else:
                review_path = self._render_review(report)
        if state.report_path != report_path or state.review_path != review_path:
            current = self._load_run(state.acceptance_run_id)
            self._store.update_run(
                state.acceptance_run_id,
                expected_revision=current.revision,
                report_path=report_path,
                review_path=review_path,
            )

    def _persist_report_artifacts(
        self,
        report: V2ProductionAcceptanceReport,
    ) -> tuple[str, str]:
        try:
            self._store.save_report(report)
            review_path = self._render_review(report)
        except (OSError, V2ProductionAcceptanceStoreError) as exc:
            raise V2ProductionAcceptanceServiceError(
                "production_acceptance_report_failed",
                "Production acceptance report could not be persisted.",
                acceptance_run_id=report.acceptance_run_id,
            ) from exc
        return (
            self._store.report_relative_path(report.acceptance_run_id),
            review_path,
        )

    def _render_review(self, report: V2ProductionAcceptanceReport) -> str:
        try:
            return self._review_renderer.render(report)
        except (OSError, V2ProductionAcceptanceStoreError) as exc:
            raise V2ProductionAcceptanceServiceError(
                "production_acceptance_report_failed",
                "Production acceptance review could not be persisted.",
                acceptance_run_id=report.acceptance_run_id,
            ) from exc

    def _heartbeat(
        self,
        acceptance_run_id: str,
        stage: str,
        *,
        lifecycle_status: str | None = None,
    ) -> V2ProductionAcceptanceRunState:
        state = self._load_run(acceptance_run_id)
        updates: dict[str, Any] = {"current_stage": stage}
        if lifecycle_status:
            updates["lifecycle_status"] = lifecycle_status
            updates["technical_verdict"] = "pending"
        return self._store.update_run(
            acceptance_run_id,
            expected_revision=state.revision,
            **updates,
        )

    def _fail(
        self,
        acceptance_run_id: str,
        code: str,
        stage: str,
        error: Exception,
        *,
        source_error_code: str | None = None,
        lifecycle_status: str = "failed",
    ) -> V2ProductionAcceptanceRunState:
        return self._fail_with_failure(
            acceptance_run_id,
            V2ProductionAcceptanceFailure(
                code=code,
                source_error_code=source_error_code or _error_code(error),
                stage=stage,
                message=_safe_message(error, self._data_dir),
            ),
            lifecycle_status=lifecycle_status,
        )

    def _fail_with_failure(
        self,
        acceptance_run_id: str,
        failure: V2ProductionAcceptanceFailure,
        *,
        lifecycle_status: str = "failed",
    ) -> V2ProductionAcceptanceRunState:
        state = self._load_run(acceptance_run_id)
        failed = self._store.update_run(
            acceptance_run_id,
            expected_revision=state.revision,
            lifecycle_status=lifecycle_status,
            technical_verdict="failed",
            current_stage=failure.stage,
            failure=failure,
            finished_at=utc_now().isoformat(),
        )
        self._ensure_terminal_report(failed)
        self._store.release_active(acceptance_run_id)
        return self._load_run(acceptance_run_id)

    def _view(
        self,
        state: V2ProductionAcceptanceRunState,
        *,
        idempotent_replay: bool = False,
    ) -> V2ProductionAcceptanceRunView:
        report_available = self._store.report_exists(state.acceptance_run_id)
        review_available = bool(
            state.review_path and self._store.review_exists(state.acceptance_run_id)
        )
        runtime = None
        if state.workflow_id:
            try:
                runtime = self._workflow_service.runtime_snapshot(state.workflow_id)
            except Exception:  # noqa: BLE001 - state remains readable during linked recovery.
                runtime = None
        return V2ProductionAcceptanceRunView(
            acceptance_run_id=state.acceptance_run_id,
            fixture_id=state.fixture_id,
            lifecycle_status=state.lifecycle_status,
            technical_verdict=state.technical_verdict,
            current_stage=state.current_stage,
            workflow_id=state.workflow_id,
            execution_id=state.execution_id,
            blockers=state.blockers,
            failure=state.failure,
            runtime=runtime,
            report_available=report_available,
            review_available=review_available,
            report_url=(
                f"/api/v2/production-acceptance-runs/{state.acceptance_run_id}/report"
                if report_available
                else None
            ),
            review_url=(
                f"/media/v2/acceptance-runs/{state.acceptance_run_id}/review.html"
                if review_available
                else None
            ),
            idempotent_replay=idempotent_replay,
            created_at=state.created_at,
            updated_at=state.updated_at,
            finished_at=state.finished_at,
        )

    def _load_run(self, acceptance_run_id: str) -> V2ProductionAcceptanceRunState:
        try:
            return self._store.load_run(acceptance_run_id)
        except V2ProductionAcceptanceStoreError as exc:
            raise _service_error_from_store(exc) from exc

    def _load_report(
        self,
        acceptance_run_id: str,
    ) -> V2ProductionAcceptanceReport | None:
        try:
            return self._store.load_report(acceptance_run_id)
        except V2ProductionAcceptanceStoreError as exc:
            raise V2ProductionAcceptanceServiceError(
                "production_acceptance_report_failed",
                "Production acceptance report could not be read.",
                acceptance_run_id=acceptance_run_id,
            ) from exc

    def _load_fixture(self, fixture_id: str) -> V2ProductionAcceptanceFixtureBundle:
        try:
            return self._fixtures.load(fixture_id)
        except V2ProductionAcceptanceFixtureRegistryError as exc:
            raise V2ProductionAcceptanceServiceError(exc.code, str(exc)) from exc


def _start_background_thread(callback: Callable[[], None]) -> None:
    thread = threading.Thread(
        target=callback,
        name="v2-production-acceptance-orchestrator",
        daemon=True,
    )
    thread.start()


def _service_error_from_store(
    error: V2ProductionAcceptanceStoreError,
) -> V2ProductionAcceptanceServiceError:
    return V2ProductionAcceptanceServiceError(
        error.code,
        str(error),
        acceptance_run_id=error.acceptance_run_id,
    )


def _value(value: Any, field: str) -> str:
    if isinstance(value, dict):
        return str(value.get(field) or "")
    return str(getattr(value, field, "") or "")


def _is_stale(updated_at: str, timeout_seconds: int) -> bool:
    try:
        timestamp = datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (utc_now() - timestamp).total_seconds() > timeout_seconds


def _error_code(error: Exception) -> str | None:
    value = getattr(error, "code", None)
    return str(value) if value else None


def _safe_message(error: Exception, data_dir: Path) -> str:
    message = str(error).replace(str(data_dir.resolve()), "[data_dir]")
    return message or "Production acceptance operation failed."


def _ffprobe_path(ffmpeg_path: str) -> str:
    path = Path(ffmpeg_path)
    return str(path.with_name("ffprobe")) if path.parent != Path(".") else "ffprobe"
