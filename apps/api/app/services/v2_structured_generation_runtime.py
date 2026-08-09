from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Generic, Literal, TypeVar, cast
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.persistence.agent_run_repository import (
    AgentRunRepository,
    AgentRunRepositoryError,
    AgentRunRecord,
)
from app.persistence.database import create_v2_database
from app.persistence.provider_model_repository import ProviderModelRepository
from app.schemas.agent_operation_contexts import PlanningAgentContext
from app.schemas.agent_runtime import AgentName, AgentRunContext, AgentRunPolicy, AgentRunRequest
from app.schemas.v2_structured_llm import V2StructuredLLMCallMetadata
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_high_risk_prompt_renderer import (
    V2HighRiskPromptRenderError,
    V2HighRiskPromptRenderer,
)
from app.services.v2_agent_event_projector import V2AgentEventProjector
from app.services.v2_agent_request_identity import agent_request_identity
from app.services.v2_prompt_registry import V2PromptRegistry
from app.services.v2_structured_generation_errors import V2StructuredLLMError
from app.services.pi_agent_runtime_client import (
    PiAgentRuntimeClient,
    PiAgentRuntimeError,
)
from app.services.provider_model_bootstrap import ProviderModelBootstrapService
from app.services.agent_run_envelope import agent_run_envelope_fields
from app.services.v2_pi_agent_context import isolate_agent_input_payload
from app.services.v2_pi_planning_session import AgentInvocation
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry

TOutput = TypeVar("TOutput", bound=BaseModel)

QualityValidator = Callable[[TOutput], None]
OutputNormalizer = Callable[[TOutput], TOutput]
RepairContextBuilder = Callable[[V2StructuredLLMError], dict[str, Any]]
FallbackBuilder = Callable[[V2StructuredLLMError], TOutput]


class QualityValidationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class StructuredGenerationRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        trace_metadata: dict[str, Any] | None = None,
        attempts: list["V2StructuredGenerationAttemptDiagnostic"] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.trace_metadata = trace_metadata or {}
        self.attempts = attempts or []


class V2StructuredGenerationAttemptDiagnostic(BaseModel):
    stage: Literal["initial", "repair", "validation", "fallback"]
    error_code: str
    message: str = Field(max_length=500)
    validation_paths: list[str] = Field(default_factory=list, max_length=30)
    violations: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    model_id: str | None = Field(default=None, max_length=200)
    retryable: bool = False


@dataclass(frozen=True)
class StructuredGenerationSpec(Generic[TOutput]):
    stage_name: str
    contract_name: str
    model_id: str
    system_prompt: str
    input_payload: dict[str, Any]
    output_model: type[TOutput]
    output_normalizer: OutputNormalizer[TOutput] | None = None
    quality_validator: QualityValidator[TOutput] | None = None
    repair_context_builder: RepairContextBuilder | None = None
    fallback_builder: FallbackBuilder[TOutput] | None = None
    trace_metadata: dict[str, Any] = field(default_factory=dict)
    validation_profile: str | None = None
    validation_context: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.3
    agent_name: AgentName | None = None
    operation: str | None = None
    tool_mode: Literal["default", "structured_only"] = "default"
    policy: AgentRunPolicy | None = None
    invocation: AgentInvocation | None = None
    agent_context: PlanningAgentContext | AgentRunContext | None = None


@dataclass(frozen=True)
class StructuredGenerationResult(Generic[TOutput]):
    output: TOutput
    mode: str
    degraded: bool
    warnings: list[dict[str, Any]]
    trace_metadata: dict[str, Any]
    original_error_code: str | None = None
    sanitized_quality_errors: list[dict[str, Any]] = field(default_factory=list)


class StructuredGenerationRuntime:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        agent_runtime_client: PiAgentRuntimeClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._agent_runtime_client = agent_runtime_client or PiAgentRuntimeClient(
            base_url=self._settings.agent_runtime_base_url,
            internal_token=self._settings.agent_runtime_internal_token or "",
            protocol_version=self._settings.agent_runtime_protocol_version,
            connect_timeout_seconds=self._settings.agent_runtime_connect_timeout_seconds,
            read_timeout_seconds=self._settings.agent_runtime_read_timeout_seconds,
            run_timeout_seconds=self._settings.agent_runtime_run_timeout_seconds,
            max_event_bytes=self._settings.agent_runtime_max_event_bytes,
            max_stream_bytes=self._settings.agent_runtime_max_stream_bytes,
        )

    def run(self, spec: StructuredGenerationSpec[TOutput]) -> StructuredGenerationResult[TOutput]:
        return self._run_pi(spec)

    def _run_pi(
        self, spec: StructuredGenerationSpec[TOutput]
    ) -> StructuredGenerationResult[TOutput]:
        database = create_v2_database(self._settings.media_data_dir)
        try:
            request = _freeze_agent_model(
                _agent_run_request(spec),
                settings=self._settings,
                repository=ProviderModelRepository(database),
            )
        except Exception:
            database.dispose()
            raise
        repository = AgentRunRepository(database)
        lease_owner_id = f"python_{uuid4().hex}"
        lease_duration = max(
            60.0,
            self._settings.agent_runtime_run_timeout_seconds * 2,
        )
        event_projector = V2AgentEventProjector(self._settings.media_data_dir)
        persisted_sequences: set[int] = set()
        lease_generation = 0

        def persist_event(event: Any) -> None:
            nonlocal lease_generation
            if event.seq in persisted_sequences:
                return
            if event.event_type == "heartbeat":
                renewed = repository.acquire_lease(
                    request.run_id,
                    lease_owner_id=lease_owner_id,
                    lease_duration_seconds=lease_duration,
                )
                lease_generation = renewed.lease_generation
            repository.record_event_seq(
                request.run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                seq=event.seq,
            )
            event_projector.consume(
                event,
                workflow_id=request.context.workflow_id,
                model_id=spec.model_id,
            )
            persisted_sequences.add(event.seq)

        try:
            record, created = repository.create_or_load(
                request,
                lease_owner_id=lease_owner_id,
                lease_duration_seconds=lease_duration,
            )
            lease_generation = record.lease_generation
            if not created:
                replay = self._existing_run_result(spec, record)
                if replay is not None:
                    return replay
                now = datetime.now(timezone.utc)
                if (
                    record.lease_owner_id is not None
                    and record.lease_expires_at is not None
                    and record.lease_expires_at > now
                ):
                    raise StructuredGenerationRuntimeError(
                        "agent_run_in_progress",
                        "The matching Agent action is already running.",
                        trace_metadata=self._trace_metadata(spec, None),
                    )
                record = repository.acquire_lease(
                    record.run_id,
                    lease_owner_id=lease_owner_id,
                    lease_duration_seconds=lease_duration,
                )
                lease_generation = record.lease_generation
                request = request.model_copy(update={"run_id": record.run_id})
                persisted_sequences.update(range(1, record.last_event_seq + 1))
            outcome = self._agent_runtime_client.run(request, on_event=persist_event)
            terminal = outcome.terminal_event
            repository.finish(
                request.run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                status={
                    "run_completed": "completed",
                    "run_failed": "failed",
                    "run_cancelled": "cancelled",
                }[terminal.event_type],
                terminal_result=terminal.payload,
                audit_metadata=(
                    terminal.payload.get("audit")
                    if isinstance(terminal.payload.get("audit"), dict)
                    else {}
                ),
                safe_error_code=(
                    str(terminal.payload.get("code") or "") or None
                    if terminal.event_type != "run_completed"
                    else None
                ),
            )
            if terminal.event_type != "run_completed":
                raise PiAgentRuntimeError(
                    str(terminal.payload.get("code") or "agent_runtime_unavailable"),
                    str(terminal.payload.get("message") or "Agent runtime failed."),
                )
            value = terminal.payload.get("value")
            output = spec.output_model.model_validate(value)
            output = self._validate_output(spec, output)
        except StructuredGenerationRuntimeError:
            raise
        except AgentRunRepositoryError as error:
            self._finish_failed_agent_run(
                repository,
                request.run_id,
                lease_owner_id,
                lease_generation,
                error,
            )
            raise StructuredGenerationRuntimeError(
                error.code,
                error.message,
                trace_metadata=self._trace_metadata(spec, None),
            ) from error
        except (PiAgentRuntimeError, QualityValidationError, ValueError) as error:
            self._finish_failed_agent_run(
                repository,
                request.run_id,
                lease_owner_id,
                lease_generation,
                error,
            )
            if isinstance(error, QualityValidationError):
                normalized = V2StructuredLLMError(
                    "structured_output_quality_failed",
                    str(error),
                    quality_error_code=error.code,
                    quality_error_message=str(error),
                    quality_error_details=error.details,
                    failure_kind="content",
                )
            else:
                normalized = V2StructuredLLMError(
                    (
                        error.code
                        if isinstance(error, PiAgentRuntimeError)
                        else "agent_structured_output_invalid"
                    ),
                    str(error),
                    failure_kind="provider_terminal",
                )
            if spec.fallback_builder is None:
                raise self._runtime_error(spec, normalized) from error
            return self._fallback(
                spec,
                normalized,
                attempts=[self._attempt_diagnostic(spec, "initial", normalized)],
            )
        except Exception as error:
            self._finish_failed_agent_run(
                repository,
                request.run_id,
                lease_owner_id,
                lease_generation,
                error,
            )
            quality_code = getattr(error, "code", None)
            if not isinstance(quality_code, str):
                raise
            normalized = V2StructuredLLMError(
                "structured_output_quality_failed",
                str(error),
                quality_error_code=quality_code,
                quality_error_message=str(error),
                quality_error_details=(
                    getattr(error, "details", None) or getattr(error, "repair_details", None)
                ),
                failure_kind="content",
            )
            if spec.fallback_builder is None:
                raise self._runtime_error(spec, normalized) from error
            return self._fallback(
                spec,
                normalized,
                attempts=[self._attempt_diagnostic(spec, "initial", normalized)],
            )
        finally:
            database.dispose()
        return self._result(
            replace(
                spec,
                trace_metadata={
                    **spec.trace_metadata,
                    "agent_run_id": request.run_id,
                },
            ),
            output=output,
            mode="pi",
            warnings=[],
            original_error=None,
            call_metadata=None,
        )

    def _existing_run_result(
        self,
        spec: StructuredGenerationSpec[TOutput],
        record: AgentRunRecord,
    ) -> StructuredGenerationResult[TOutput] | None:
        if record.status == "completed":
            value = (record.terminal_result or {}).get("value")
            output = spec.output_model.model_validate(value)
            output = self._validate_output(spec, output)
            replay_spec = replace(
                spec,
                trace_metadata={
                    **spec.trace_metadata,
                    "agent_run_replayed": True,
                    "agent_run_id": record.run_id,
                },
            )
            return self._result(
                replay_spec,
                output=output,
                mode="pi",
                warnings=[],
                original_error=None,
                call_metadata=None,
            )
        if record.status in {"failed", "cancelled"}:
            raise StructuredGenerationRuntimeError(
                record.safe_error_code or f"agent_run_{record.status}",
                "The matching Agent action is already terminal.",
                trace_metadata={
                    **self._trace_metadata(spec, None),
                    "agent_run_replayed": True,
                    "agent_run_id": record.run_id,
                },
            )
        return None

    @staticmethod
    def _finish_failed_agent_run(
        repository: AgentRunRepository,
        run_id: str,
        lease_owner_id: str,
        lease_generation: int,
        error: Exception,
    ) -> None:
        try:
            record = repository.load(run_id)
            if record.status in {"completed", "failed", "cancelled"}:
                return
            code = str(getattr(error, "code", None) or "agent_runtime_unavailable")
            repository.finish(
                run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                status="failed",
                terminal_result={"code": code, "message": "Agent runtime failed."},
                safe_error_code=code,
            )
        except Exception:
            return

    def _fallback(
        self,
        spec: StructuredGenerationSpec[TOutput],
        error: V2StructuredLLMError,
        *,
        attempts: list[V2StructuredGenerationAttemptDiagnostic],
    ) -> StructuredGenerationResult[TOutput]:
        if spec.fallback_builder is None:
            raise self._runtime_error(spec, error, attempts=attempts) from error
        fallback_prompt = _render_runtime_high_risk_prompt(
            prompt_id="v2.fallback.deterministic_generation.v1",
            spec=spec,
            path_kind="fallback",
            context={
                "stage_name": spec.stage_name,
                "contract_name": spec.contract_name,
            },
        )
        try:
            output = spec.fallback_builder(error)
            attempts.append(self._attempt_diagnostic(spec, "fallback", error))
            output = self._validate_output(spec, output)
        except Exception as exc:
            if not attempts or attempts[-1].stage != "fallback":
                attempts.append(self._attempt_diagnostic(spec, "fallback", error))
            attempts.append(self._attempt_diagnostic(spec, "validation", exc))
            raise StructuredGenerationRuntimeError(
                "structured_generation_fallback_failed",
                "Structured generation fallback failed validation.",
                trace_metadata=self._trace_metadata(spec, error),
                attempts=attempts,
            ) from exc
        warning = {
            "code": "structured_generation_fallback_used",
            "stage_name": spec.stage_name,
            "original_error_code": error.code,
            "prompt_registry_ref": fallback_prompt["prompt_registry_ref"],
            "prompt_lineage": fallback_prompt["prompt_lineage"],
        }
        return self._result(
            spec,
            output=output,
            mode="fallback",
            warnings=[warning],
            original_error=error,
            call_metadata=error.call_metadata,
        )

    def _validate_output(
        self,
        spec: StructuredGenerationSpec[TOutput],
        output: BaseModel,
    ) -> TOutput:
        if not isinstance(output, spec.output_model):
            output = spec.output_model.model_validate(output.model_dump(mode="json"))
        normalized = cast(TOutput, output)
        if spec.output_normalizer is not None:
            normalized = spec.output_normalizer(normalized)
            if not isinstance(normalized, spec.output_model):
                normalized = spec.output_model.model_validate(normalized.model_dump(mode="json"))
        if spec.quality_validator is not None:
            spec.quality_validator(normalized)
        return normalized

    def _result(
        self,
        spec: StructuredGenerationSpec[TOutput],
        *,
        output: TOutput,
        mode: str,
        warnings: list[dict[str, Any]],
        original_error: V2StructuredLLMError | None,
        call_metadata: V2StructuredLLMCallMetadata | None,
    ) -> StructuredGenerationResult[TOutput]:
        sanitized_warnings = sanitize_context_for_llm_text(warnings)
        output = _with_output_warnings(output, sanitized_warnings)
        return StructuredGenerationResult(
            output=output,
            mode=mode,
            degraded=mode == "fallback",
            warnings=sanitized_warnings,
            trace_metadata=self._trace_metadata(
                spec,
                original_error,
                call_metadata=call_metadata,
                path_kind=_path_kind_for_result_mode(mode),
            ),
            original_error_code=original_error.code if original_error else None,
            sanitized_quality_errors=_quality_errors(original_error),
        )

    def _runtime_error(
        self,
        spec: StructuredGenerationSpec[TOutput],
        error: V2StructuredLLMError,
        *,
        attempts: list[V2StructuredGenerationAttemptDiagnostic] | None = None,
    ) -> StructuredGenerationRuntimeError:
        return StructuredGenerationRuntimeError(
            self._generic_error_code(error),
            _safe_error_message(error),
            trace_metadata=self._trace_metadata(spec, error),
            attempts=attempts or [self._attempt_diagnostic(spec, "initial", error)],
        )

    def _attempt_diagnostic(
        self,
        spec: StructuredGenerationSpec[TOutput],
        stage: Literal["initial", "repair", "validation", "fallback"],
        error: Exception,
    ) -> V2StructuredGenerationAttemptDiagnostic:
        if isinstance(error, V2StructuredLLMError):
            error_code = self._generic_error_code(error)
            validation_paths = list(error.validation_error_paths)[:30]
            violations = _quality_errors(error)
        elif isinstance(error, QualityValidationError):
            error_code = error.code
            validation_paths = []
            violations = [sanitize_context_for_llm_text(error.details)] if error.details else []
        else:
            error_code = "structured_generation_fallback_failed"
            validation_paths = []
            violations = []
        return V2StructuredGenerationAttemptDiagnostic(
            stage=stage,
            error_code=error_code,
            message=_safe_error_message(error),
            validation_paths=validation_paths,
            violations=violations[:30],
            model_id=spec.model_id[:200] or None,
            retryable=(
                stage == "initial"
                and isinstance(error, V2StructuredLLMError)
                and error.failure_kind == "content"
            ),
        )

    def _trace_metadata(
        self,
        spec: StructuredGenerationSpec[TOutput],
        error: V2StructuredLLMError | None,
        *,
        call_metadata: V2StructuredLLMCallMetadata | None = None,
        path_kind: str | None = None,
    ) -> dict[str, Any]:
        metadata = {
            **sanitize_context_for_llm_text(spec.trace_metadata),
            "stage_name": spec.stage_name,
            "contract_name": spec.contract_name,
            "model_id": spec.model_id,
        }
        if error is not None:
            metadata["error_code"] = self._generic_error_code(error)
            metadata["quality_errors"] = _quality_errors(error)
        effective_call_metadata = call_metadata or (error.call_metadata if error else None)
        if effective_call_metadata is not None:
            metadata["llm_call"] = effective_call_metadata.model_dump(mode="json")
        lineage = _structured_prompt_lineage(spec, metadata, path_kind=path_kind)
        if lineage:
            metadata.update(lineage)
        return sanitize_context_for_llm_text(metadata)

    def _generic_error_code(self, error: V2StructuredLLMError) -> str:
        if error.code == "structured_llm_unavailable":
            return "structured_generation_unavailable"
        if error.code in {
            "agent_structured_output_invalid",
            "structured_output_invalid_json",
            "structured_output_schema_invalid",
        }:
            return "structured_generation_schema_failed"
        if error.code == "structured_output_quality_failed":
            return "structured_generation_quality_failed"
        if error.code == "structured_generation_repair_failed":
            return "structured_generation_repair_failed"
        return "structured_generation_unavailable"


def _agent_run_request(spec: StructuredGenerationSpec[Any]) -> AgentRunRequest:
    payload = isolate_agent_input_payload(sanitize_context_for_llm_text(spec.input_payload))
    workflow_id = str(spec.trace_metadata.get("workflow_id") or "") or None
    timeout_seconds = (
        spec.policy.timeout_seconds
        if spec.policy is not None
        else float(spec.trace_metadata.get("timeout_seconds", 120.0))
    )
    operation = spec.operation or _agent_operation(spec)
    VideoAgentOperationRegistry().resolve(operation)
    invocation = spec.invocation
    agent_name: AgentName = "video_agent"
    model_policy_id = f"{agent_name}.{operation}.v1"
    if invocation is not None and invocation.model_policy_id != model_policy_id:
        raise ValueError("agent_model_policy_mismatch")
    context = spec.agent_context or AgentRunContext(
        operation=operation,
        user_input=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        workflow_id=workflow_id,
        input_payload=payload,
        contract_schema=spec.output_model.model_json_schema(),
    )
    identity = None
    action_id = str(spec.trace_metadata.get("action_id") or "").strip()
    if invocation is None and action_id:
        target = getattr(context, "target", None)
        target_revision = (
            target.expected_revision
            if target is not None
            else spec.trace_metadata.get("expected_target_revision")
        )
        identity = agent_request_identity(
            conversation_id=(
                getattr(context, "conversation_id", None)
                or str(spec.trace_metadata.get("conversation_id") or "").strip()
                or None
            ),
            action_id=action_id,
            operation=operation,
            target_revision=int(target_revision) if target_revision is not None else None,
            normalized_input=context,
        )
    expected_target_revision = getattr(
        getattr(context, "target", None), "expected_revision", None
    ) or spec.trace_metadata.get("expected_target_revision")
    run_id = (
        invocation.run_id
        if invocation
        else identity.run_id
        if identity is not None
        else f"arun_{uuid4().hex}"
    )
    policy = (
        AgentRunPolicy(timeout_seconds=invocation.timeout_seconds)
        if invocation
        else spec.policy or AgentRunPolicy(timeout_seconds=timeout_seconds)
    ).model_copy(update={"max_handoffs": 0})
    return AgentRunRequest(
        run_id=run_id,
        request_id=(
            invocation.request_id
            if invocation
            else identity.request_id
            if identity is not None
            else f"req_{uuid4().hex}"
        ),
        **agent_run_envelope_fields(context),
        parent_run_id=invocation.parent_run_id if invocation else None,
        agent_name=agent_name,
        operation=operation,
        deadline_at=(
            invocation.deadline_at
            if invocation
            else datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
        ),
        model_policy_id=model_policy_id,
        contract_name=spec.contract_name,
        validation_profile=spec.validation_profile,
        validation_context=sanitize_context_for_llm_text(spec.validation_context),
        context=context,
        policy=policy,
        credential_ref="llm-default",
        audit_metadata={
            "stage_name": spec.stage_name,
            "contract_name": spec.contract_name,
            "workflow_id": workflow_id,
            "model_policy_id": model_policy_id,
            "result_contract_name": spec.contract_name,
            "context_snapshot_id": agent_run_envelope_fields(context)["context_snapshot_id"],
            "max_handoffs": policy.max_handoffs,
            **({"tool_mode": spec.tool_mode} if spec.tool_mode != "default" else {}),
            **(
                {"expected_target_revision": int(expected_target_revision)}
                if expected_target_revision is not None
                else {}
            ),
            **({"request_identity_digest": identity.input_digest} if identity is not None else {}),
        },
        contract_schema=spec.output_model.model_json_schema(),
    )


def _freeze_agent_model(
    request: AgentRunRequest,
    *,
    settings: Settings,
    repository: ProviderModelRepository,
) -> AgentRunRequest:
    defaults = repository.get_defaults()
    if "agent" not in defaults:
        ProviderModelBootstrapService(settings, repository).bootstrap(
            now=datetime.now(timezone.utc).isoformat()
        )
        defaults = repository.get_defaults()
    default = defaults.get("agent")
    if default is None:
        raise StructuredGenerationRuntimeError(
            "agent_model_unavailable",
            "The installation Agent model default is not configured.",
        )
    return request.model_copy(
        update={
            "model_ref": default.model_ref,
            "audit_metadata": {
                **request.audit_metadata,
                "model_ref": default.model_ref,
                "model_default_revision": default.revision,
            },
        }
    )


def _agent_operation(spec: StructuredGenerationSpec[Any]) -> str:
    if spec.stage_name != "specialist_materializer":
        return spec.stage_name
    if spec.contract_name.startswith("V2Product"):
        return "product_prompt"
    if spec.contract_name.startswith("V2Character"):
        return "character_prompt"
    if spec.contract_name.startswith("V2Scene"):
        return "scene_prompt"
    if spec.contract_name == "V2ShotCellPromptPlan":
        return "storyboard_prompt"
    if spec.contract_name == "V2ShotVideoPromptPlan":
        return "shot_video_prompt"
    if spec.contract_name == "V2BgmPromptPlan":
        return "bgm_prompt"
    return spec.stage_name


def _with_output_warnings(output: TOutput, warnings: list[dict[str, Any]]) -> TOutput:
    if not warnings or not hasattr(output, "warnings"):
        return output
    existing = getattr(output, "warnings", [])
    return output.model_copy(update={"warnings": [*existing, *warnings]})


def _quality_errors(error: V2StructuredLLMError | None) -> list[dict[str, Any]]:
    if error is None:
        return []
    if error.quality_error_code or error.quality_error_message or error.quality_error_details:
        return [
            sanitize_context_for_llm_text(
                {
                    "code": error.quality_error_code,
                    "message": error.quality_error_message,
                    "details": error.quality_error_details,
                }
            )
        ]
    return []


def _structured_prompt_lineage(
    spec: StructuredGenerationSpec[Any],
    metadata: dict[str, Any],
    *,
    path_kind: str | None = None,
) -> dict[str, Any]:
    del spec, metadata, path_kind
    return {}


def _render_runtime_high_risk_prompt(
    *,
    prompt_id: str,
    spec: StructuredGenerationSpec[Any],
    path_kind: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    try:
        render_result = V2HighRiskPromptRenderer().render(
            prompt_id=prompt_id,
            context=context,
            identity={
                "workflow_id": str(spec.trace_metadata.get("workflow_id") or "") or None,
                "node_id": str(spec.trace_metadata.get("node_id") or "") or None,
                "item_id": str(spec.trace_metadata.get("item_id") or "") or None,
                "slot_id": str(spec.trace_metadata.get("slot_id") or "") or None,
                "slot_type": str(spec.trace_metadata.get("slot_type") or "") or None,
                "path_kind": path_kind,
            },
        )
    except V2HighRiskPromptRenderError as exc:
        raise StructuredGenerationRuntimeError(
            exc.code,
            str(exc),
            trace_metadata=exc.metadata,
        ) from exc
    lineage = V2PromptRegistry().lineage_for_render(render_result).model_dump(mode="json")
    return {
        "prompt_text": render_result.prompt_text,
        "prompt_registry_ref": render_result.prompt_registry_ref.model_dump(mode="json"),
        "prompt_lineage": lineage,
    }


def _path_kind_for_result_mode(mode: str) -> str:
    if mode == "fallback":
        return "fallback"
    if mode == "repair":
        return "repair"
    return "normal"


def _safe_error_message(error: V2StructuredLLMError) -> str:
    message = str(error).strip() or error.code
    return message[:500]
