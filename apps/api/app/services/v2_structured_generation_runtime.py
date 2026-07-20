from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.schemas.v2_structured_llm import V2StructuredLLMCallMetadata
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_high_risk_prompt_renderer import (
    V2HighRiskPromptRenderError,
    V2HighRiskPromptRenderer,
)
from app.services.v2_prompt_registry import V2PromptRegistry
from app.services.v2_runtime_prompt_packs import prompt_content_profile_metadata
from app.services.v2_structured_llm import (
    V2StructuredLLMClient,
    V2StructuredLLMError,
)

TOutput = TypeVar("TOutput", bound=BaseModel)

QualityValidator = Callable[[TOutput], None]
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
    quality_validator: QualityValidator[TOutput] | None = None
    repair_context_builder: RepairContextBuilder | None = None
    fallback_builder: FallbackBuilder[TOutput] | None = None
    trace_metadata: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.3


@dataclass(frozen=True)
class StructuredGenerationResult(Generic[TOutput]):
    output: TOutput
    mode: str
    warnings: list[dict[str, Any]]
    trace_metadata: dict[str, Any]
    original_error_code: str | None = None
    sanitized_quality_errors: list[dict[str, Any]] = field(default_factory=list)


class StructuredGenerationRuntime:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        structured_llm: V2StructuredLLMClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._structured_llm = structured_llm or V2StructuredLLMClient(self._settings)

    def run(self, spec: StructuredGenerationSpec[TOutput]) -> StructuredGenerationResult[TOutput]:
        try:
            output, warnings, call_metadata = self._generate_once(
                spec,
                spec.input_payload,
                attempt_kind="initial",
            )
            return self._result(
                spec,
                output=output,
                mode="llm",
                warnings=warnings,
                original_error=None,
                call_metadata=call_metadata,
            )
        except V2StructuredLLMError as first_error:
            if spec.fallback_builder is None:
                raise self._runtime_error(spec, first_error) from first_error
            return self._repair_or_fallback(spec, first_error)

    def _repair_or_fallback(
        self,
        spec: StructuredGenerationSpec[TOutput],
        first_error: V2StructuredLLMError,
    ) -> StructuredGenerationResult[TOutput]:
        attempts = [self._attempt_diagnostic(spec, "initial", first_error)]
        if first_error.failure_kind != "content":
            return self._fallback(spec, first_error, attempts=attempts)
        repair_context = self._repair_context(spec, first_error)
        repair_prompt = _render_runtime_high_risk_prompt(
            prompt_id="v2.repair.structured_generation.v1",
            spec=spec,
            path_kind="repair",
            context={
                "stage_name": spec.stage_name,
                "contract_name": spec.contract_name,
            },
        )
        repair_payload = sanitize_context_for_llm_text(
            {
                "repair": True,
                "instruction": repair_prompt["prompt_text"],
                "prompt_registry_ref": repair_prompt["prompt_registry_ref"],
                "prompt_lineage": repair_prompt["prompt_lineage"],
                "stage_name": spec.stage_name,
                "contract_name": spec.contract_name,
                "original_request": spec.input_payload,
                "repair_context": repair_context,
                "quality_repair_context": repair_context,
                "validation_error_paths": list(repair_context.get("schema_error_paths") or []),
            }
        )
        try:
            output, warnings, call_metadata = self._generate_once(
                spec,
                repair_payload,
                attempt_kind="repair",
            )
            repair_warning = {
                "code": "structured_generation_repair_used",
                "stage_name": spec.stage_name,
                "original_error_code": self._generic_error_code(first_error),
            }
            return self._result(
                spec,
                output=output,
                mode="repair",
                warnings=[*warnings, repair_warning],
                original_error=first_error,
                call_metadata=call_metadata,
            )
        except V2StructuredLLMError as repair_error:
            fallback_error = V2StructuredLLMError(
                "structured_generation_repair_failed",
                str(repair_error),
                validation_error_paths=repair_error.validation_error_paths,
                quality_error_code=repair_error.quality_error_code,
                quality_error_message=repair_error.quality_error_message,
                quality_error_details=repair_error.quality_error_details,
                failure_kind=repair_error.failure_kind,
                call_metadata=repair_error.call_metadata,
            )
            attempts.append(self._attempt_diagnostic(spec, "repair", repair_error))
            return self._fallback(spec, fallback_error, attempts=attempts)

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

    def _generate_once(
        self,
        spec: StructuredGenerationSpec[TOutput],
        payload: dict[str, Any],
        *,
        attempt_kind: Literal["initial", "repair"],
    ) -> tuple[TOutput, list[dict[str, Any]], V2StructuredLLMCallMetadata | None]:
        result = self._structured_llm.generate(
            model_id=spec.model_id,
            system_prompt=spec.system_prompt,
            user_payload=payload,
            output_model=spec.output_model,
            contract_name=spec.contract_name,
            quality_validator=spec.quality_validator,
            temperature=spec.temperature,
            repair_on_failure=False,
            stage_name=spec.stage_name,
            attempt_kind=attempt_kind,
        )
        output = self._validate_output(spec, result.output)
        return (
            output,
            sanitize_context_for_llm_text(result.warnings),
            getattr(result, "call_metadata", None),
        )

    def _validate_output(
        self,
        spec: StructuredGenerationSpec[TOutput],
        output: BaseModel,
    ) -> TOutput:
        if not isinstance(output, spec.output_model):
            output = spec.output_model.model_validate(output.model_dump(mode="json"))
        if spec.quality_validator is not None:
            spec.quality_validator(output)
        return output

    def _repair_context(
        self,
        spec: StructuredGenerationSpec[TOutput],
        error: V2StructuredLLMError,
    ) -> dict[str, Any]:
        base = {
            "stage_name": spec.stage_name,
            "contract_name": spec.contract_name,
            "schema_error_paths": list(error.validation_error_paths),
            "quality_error_code": error.quality_error_code,
            "quality_error_message": error.quality_error_message,
            "quality_error_details": error.quality_error_details,
            "error_code": self._generic_error_code(error),
            "error_message": _safe_error_message(error),
        }
        if spec.repair_context_builder is not None:
            base.update(spec.repair_context_builder(error))
        return sanitize_context_for_llm_text(base)

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
        if error.code in {"structured_output_invalid_json", "structured_output_schema_invalid"}:
            return "structured_generation_schema_failed"
        if error.code == "structured_output_quality_failed":
            return "structured_generation_quality_failed"
        if error.code == "structured_generation_repair_failed":
            return "structured_generation_repair_failed"
        return "structured_generation_unavailable"


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
    prompt_id = _structured_prompt_id(spec.stage_name)
    if not prompt_id:
        return {}
    registry = V2PromptRegistry()
    render_result = registry.render_result_for_prompt_id(
        prompt_id=prompt_id,
        rendered_prompt=spec.system_prompt,
        render_context={
            "input_payload": spec.input_payload,
            "contract_name": spec.contract_name,
            "stage_name": spec.stage_name,
        },
        workflow_id=str(metadata.get("workflow_id") or "") or None,
        node_id=str(metadata.get("node_id") or "") or None,
        item_id=str(metadata.get("item_id") or "") or None,
        slot_id=str(metadata.get("slot_id") or "") or None,
        slot_type=str(metadata.get("slot_type") or "") or None,
        path_kind=path_kind or _path_kind_for_mode(metadata),
    )
    lineage = registry.lineage_for_render(render_result).model_dump(mode="json")
    payload = {
        "prompt_registry_ref": render_result.prompt_registry_ref.model_dump(mode="json"),
        "prompt_lineage": lineage,
    }
    profile = prompt_content_profile_metadata(
        prompt_id=prompt_id,
        prompt_text=spec.system_prompt,
    )
    if profile is not None:
        payload["prompt_content_profile"] = profile
    return payload


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


def _structured_prompt_id(stage_name: str) -> str | None:
    if stage_name == "script_writer":
        return "v2.script_writer.plan.v1"
    if stage_name == "expert_brief_planner":
        return "v2.expert_brief.plan.v1"
    if stage_name == "storyboard_detail":
        return "v2.storyboard.detail.v1"
    return None


def _path_kind_for_mode(metadata: dict[str, Any]) -> str:
    if metadata.get("error_code") == "structured_generation_repair_failed":
        return "fallback"
    if metadata.get("error_code"):
        return "repair"
    return "normal"


def _path_kind_for_result_mode(mode: str) -> str:
    if mode == "fallback":
        return "fallback"
    if mode == "repair":
        return "repair"
    return "normal"


def _safe_error_message(error: V2StructuredLLMError) -> str:
    message = str(error).strip() or error.code
    return message[:500]
