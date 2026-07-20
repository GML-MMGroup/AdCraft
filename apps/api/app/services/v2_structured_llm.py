from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import time
from typing import Any, Literal, TypeVar

from openai import APIConnectionError, APITimeoutError, OpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.llm_call_policy import (
    V2LLMAttemptKind,
    V2LLMCallPolicyResolver,
    V2ResolvedLLMCallPolicy,
)
from app.schemas.v2_structured_llm import V2StructuredLLMCallMetadata
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text_with_warnings
from app.services.v2_high_risk_prompt_renderer import (
    V2HighRiskPromptRenderError,
    V2HighRiskPromptRenderer,
)
from app.services.v2_prompt_registry import V2PromptRegistry

TModel = TypeVar("TModel", bound=BaseModel)
QualityValidator = Callable[[TModel], None]
V2StructuredLLMFailureKind = Literal[
    "configuration",
    "provider_transient",
    "provider_terminal",
    "content",
]
ClientFactory = Callable[..., Any]
Sleeper = Callable[[float], None]
Clock = Callable[[], float]


class V2StructuredLLMError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        invalid_output: Any | None = None,
        validation_error_paths: list[str] | None = None,
        quality_error_code: str | None = None,
        quality_error_message: str | None = None,
        quality_error_details: dict[str, Any] | None = None,
        failure_kind: V2StructuredLLMFailureKind | None = None,
        call_metadata: V2StructuredLLMCallMetadata | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.invalid_output = invalid_output
        self.validation_error_paths = validation_error_paths or []
        self.quality_error_code = quality_error_code
        self.quality_error_message = quality_error_message
        self.quality_error_details = quality_error_details or {}
        self.failure_kind = failure_kind or _failure_kind_for_code(code)
        self.call_metadata = call_metadata


@dataclass(frozen=True)
class V2StructuredLLMResult:
    output: BaseModel
    warnings: list[dict[str, Any]]
    call_metadata: V2StructuredLLMCallMetadata | None = None


@dataclass(frozen=True)
class _CompletionResult:
    response: Any
    call_metadata: V2StructuredLLMCallMetadata


class V2StructuredLLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: ClientFactory | None = None,
        sleeper: Sleeper | None = None,
        monotonic: Clock | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._sleeper = sleeper or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._policy_resolver = V2LLMCallPolicyResolver(
            transient_retry_delay_seconds=settings.llm_transient_retry_delay_seconds
        )

    def generate(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[TModel],
        contract_name: str,
        quality_validator: QualityValidator[TModel] | None = None,
        temperature: float = 0.3,
        repair_on_failure: bool = True,
        stage_name: str = "agent_default",
        attempt_kind: V2LLMAttemptKind = "initial",
    ) -> V2StructuredLLMResult:
        sanitized_payload, warnings = sanitize_context_for_llm_text_with_warnings(user_payload)
        response_format = _json_schema_response_format(output_model, contract_name)
        schema_supported = True
        try:
            completion = self._create_completion(
                model_id=model_id,
                system_prompt=system_prompt,
                user_payload=sanitized_payload,
                response_format=response_format,
                temperature=temperature,
                stage_name=stage_name,
                attempt_kind=attempt_kind,
            )
        except Exception as exc:  # noqa: BLE001 - SDK errors are normalized below.
            if not _is_json_schema_rejection(exc):
                raise self._normalize_external_error(
                    exc,
                    stage_name=stage_name,
                    attempt_kind=attempt_kind,
                    response_format=response_format,
                ) from exc
            schema_supported = False
            warnings.append(
                {
                    "code": "structured_output_json_schema_unsupported",
                    "message": "Provider rejected json_schema response_format; retried with json_object.",
                }
            )
            response_format = {"type": "json_object"}
            try:
                completion = self._create_completion(
                    model_id=model_id,
                    system_prompt=system_prompt,
                    user_payload=sanitized_payload,
                    response_format=response_format,
                    temperature=temperature,
                    stage_name=stage_name,
                    attempt_kind=attempt_kind,
                )
            except Exception as fallback_exc:  # noqa: BLE001
                raise self._normalize_external_error(
                    fallback_exc,
                    stage_name=stage_name,
                    attempt_kind=attempt_kind,
                    response_format=response_format,
                ) from fallback_exc

        response, call_metadata = self._unpack_completion(
            completion,
            stage_name=stage_name,
            attempt_kind=attempt_kind,
            response_format=response_format,
        )
        content = _extract_message_content(response)
        try:
            model = _parse_and_validate(
                content,
                output_model=output_model,
                quality_validator=quality_validator,
            )
        except V2StructuredLLMError as first_error:
            first_error.call_metadata = call_metadata
            if not repair_on_failure:
                raise
            repair_payload = _repair_payload(
                contract_name=contract_name,
                output_model=output_model,
                original_payload=sanitized_payload,
                invalid_output=first_error.invalid_output,
                error=first_error,
            )
            repair_format = response_format if schema_supported else {"type": "json_object"}
            try:
                repair_completion = self._create_completion(
                    model_id=model_id,
                    system_prompt=system_prompt,
                    user_payload=repair_payload,
                    response_format=repair_format,
                    temperature=temperature,
                    stage_name=stage_name,
                    attempt_kind="repair",
                )
                repair_response, call_metadata = self._unpack_completion(
                    repair_completion,
                    stage_name=stage_name,
                    attempt_kind="repair",
                    response_format=repair_format,
                )
                repair_content = _extract_message_content(repair_response)
                model = _parse_and_validate(
                    repair_content,
                    output_model=output_model,
                    quality_validator=quality_validator,
                )
            except V2StructuredLLMError as repair_error:
                if repair_error.call_metadata is None:
                    repair_error.call_metadata = call_metadata
                raise
            except Exception as exc:  # noqa: BLE001 - repair call failures are normalized.
                raise self._normalize_external_error(
                    exc,
                    stage_name=stage_name,
                    attempt_kind="repair",
                    response_format=repair_format,
                ) from exc

        return V2StructuredLLMResult(
            output=_with_warnings(model, warnings),
            warnings=warnings,
            call_metadata=call_metadata,
        )

    def _create_completion(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_format: dict[str, Any],
        temperature: float,
        stage_name: str = "agent_default",
        attempt_kind: V2LLMAttemptKind = "initial",
    ) -> _CompletionResult:
        policy = self._policy_resolver.resolve(
            provider_id=self._settings.llm_provider,
            stage_name=stage_name,
            attempt_kind=attempt_kind,
        )
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise V2StructuredLLMError(
                "structured_llm_unavailable",
                "LLM API key and base URL are required.",
                failure_kind="configuration",
                call_metadata=_call_metadata(
                    policy=policy,
                    response_format=response_format,
                    attempt_count=0,
                    transient_retry_used=False,
                    elapsed_ms=0,
                    error_code="structured_llm_unavailable",
                ),
            )

        client_factory = self._client_factory or OpenAI
        client = client_factory(
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url,
            timeout=policy.timeout_seconds,
            max_retries=policy.sdk_max_retries,
        )
        request: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            "response_format": response_format,
            "temperature": temperature,
            "max_tokens": policy.max_output_tokens,
        }
        if policy.provider_request_options:
            request["extra_body"] = dict(policy.provider_request_options)

        started_at = self._monotonic()
        attempt_count = 0
        transient_retry_used = False
        while True:
            attempt_count += 1
            try:
                response = client.chat.completions.create(**request)
            except Exception as exc:  # noqa: BLE001 - provider errors are normalized.
                if _is_json_schema_rejection(exc):
                    raise V2StructuredLLMError(
                        "structured_output_json_schema_unsupported",
                        str(exc),
                        failure_kind="provider_terminal",
                        call_metadata=_call_metadata(
                            policy=policy,
                            response_format=response_format,
                            attempt_count=attempt_count,
                            transient_retry_used=transient_retry_used,
                            elapsed_ms=_elapsed_ms(started_at, self._monotonic()),
                            error_code="structured_output_json_schema_unsupported",
                        ),
                    ) from exc
                classified = _classify_provider_error(exc)
                can_retry = classified.retryable and attempt_count <= policy.max_transient_retries
                if can_retry:
                    transient_retry_used = True
                    self._sleeper(policy.transient_retry_delay_seconds)
                    continue
                raise V2StructuredLLMError(
                    classified.code,
                    str(exc),
                    failure_kind=classified.failure_kind,
                    call_metadata=_call_metadata(
                        policy=policy,
                        response_format=response_format,
                        attempt_count=attempt_count,
                        transient_retry_used=transient_retry_used,
                        elapsed_ms=_elapsed_ms(started_at, self._monotonic()),
                        error_code=classified.code,
                    ),
                ) from exc

            return _CompletionResult(
                response=response,
                call_metadata=_call_metadata(
                    policy=policy,
                    response_format=response_format,
                    attempt_count=attempt_count,
                    transient_retry_used=transient_retry_used,
                    elapsed_ms=_elapsed_ms(started_at, self._monotonic()),
                    response=response,
                ),
            )

    def _unpack_completion(
        self,
        completion: Any,
        *,
        stage_name: str,
        attempt_kind: V2LLMAttemptKind,
        response_format: dict[str, Any],
    ) -> tuple[Any, V2StructuredLLMCallMetadata]:
        if isinstance(completion, _CompletionResult):
            return completion.response, completion.call_metadata
        policy = self._policy_resolver.resolve(
            provider_id=self._settings.llm_provider,
            stage_name=stage_name,
            attempt_kind=attempt_kind,
        )
        return completion, _call_metadata(
            policy=policy,
            response_format=response_format,
            attempt_count=1,
            transient_retry_used=False,
            elapsed_ms=0,
            response=completion,
        )

    def _normalize_external_error(
        self,
        exc: Exception,
        *,
        stage_name: str,
        attempt_kind: V2LLMAttemptKind,
        response_format: dict[str, Any],
    ) -> V2StructuredLLMError:
        if isinstance(exc, V2StructuredLLMError):
            return exc
        policy = self._policy_resolver.resolve(
            provider_id=self._settings.llm_provider,
            stage_name=stage_name,
            attempt_kind=attempt_kind,
        )
        classified = _classify_provider_error(exc)
        return V2StructuredLLMError(
            classified.code,
            str(exc),
            failure_kind=classified.failure_kind,
            call_metadata=_call_metadata(
                policy=policy,
                response_format=response_format,
                attempt_count=1,
                transient_retry_used=False,
                elapsed_ms=0,
                error_code=classified.code,
            ),
        )


@dataclass(frozen=True)
class _ProviderErrorClassification:
    code: str
    failure_kind: V2StructuredLLMFailureKind
    retryable: bool


def _failure_kind_for_code(code: str) -> V2StructuredLLMFailureKind:
    if code == "structured_llm_unavailable":
        return "configuration"
    if code in {
        "structured_llm_rate_limited",
        "structured_llm_provider_overloaded",
        "structured_llm_connection_failed",
        "structured_llm_timeout",
    }:
        return "provider_transient"
    if code.startswith("structured_output_"):
        return "content"
    return "provider_terminal"


def _classify_provider_error(exc: Exception) -> _ProviderErrorClassification:
    if isinstance(exc, (APITimeoutError, TimeoutError)):
        return _ProviderErrorClassification(
            code="structured_llm_timeout",
            failure_kind="provider_transient",
            retryable=False,
        )

    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return _ProviderErrorClassification(
            code="structured_llm_rate_limited",
            failure_kind="provider_transient",
            retryable=True,
        )
    if status_code in {500, 502, 503, 504}:
        return _ProviderErrorClassification(
            code="structured_llm_provider_overloaded",
            failure_kind="provider_transient",
            retryable=True,
        )
    if isinstance(exc, (APIConnectionError, ConnectionError)):
        return _ProviderErrorClassification(
            code="structured_llm_connection_failed",
            failure_kind="provider_transient",
            retryable=True,
        )
    return _ProviderErrorClassification(
        code="structured_llm_call_failed",
        failure_kind="provider_terminal",
        retryable=False,
    )


def _call_metadata(
    *,
    policy: V2ResolvedLLMCallPolicy,
    response_format: dict[str, Any],
    attempt_count: int,
    transient_retry_used: bool,
    elapsed_ms: int,
    response: Any | None = None,
    error_code: str | None = None,
) -> V2StructuredLLMCallMetadata:
    usage = _value_at(response, "usage")
    completion_details = _value_at(usage, "completion_tokens_details")
    first_choice = _first(_value_at(response, "choices"))
    return V2StructuredLLMCallMetadata(
        provider_id=policy.provider_id,
        stage_name=policy.stage_name,
        attempt_kind=policy.attempt_kind,
        reasoning_mode=policy.reasoning_mode.value,
        thinking_budget=policy.thinking_budget,
        timeout_seconds=policy.timeout_seconds,
        max_tokens=policy.max_output_tokens,
        attempt_count=attempt_count,
        transient_retry_used=transient_retry_used,
        elapsed_ms=elapsed_ms,
        response_format=str(response_format.get("type") or "json_object"),
        prompt_tokens=_non_negative_int(_value_at(usage, "prompt_tokens")),
        completion_tokens=_non_negative_int(_value_at(usage, "completion_tokens")),
        reasoning_tokens=_non_negative_int(_value_at(completion_details, "reasoning_tokens")),
        finish_reason=_bounded_text(_value_at(first_choice, "finish_reason"), 64),
        error_code=error_code,
    )


def _elapsed_ms(started_at: float, finished_at: float) -> int:
    return max(0, round((finished_at - started_at) * 1_000))


def _value_at(value: Any, field: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _first(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _bounded_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    return str(value)[:max_length]


def _json_schema_response_format(
    output_model: type[BaseModel],
    contract_name: str,
) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": contract_name,
            "schema": output_model.model_json_schema(),
            "strict": True,
        },
    }


def _parse_and_validate(
    content: str,
    *,
    output_model: type[TModel],
    quality_validator: QualityValidator[TModel] | None,
) -> TModel:
    try:
        raw_output = json.loads(content)
    except json.JSONDecodeError as exc:
        raise V2StructuredLLMError(
            "structured_output_invalid_json",
            "Structured LLM output was not valid JSON.",
            invalid_output=content,
        ) from exc
    if not isinstance(raw_output, dict):
        raise V2StructuredLLMError(
            "structured_output_schema_invalid",
            "Structured LLM output must be a JSON object.",
            invalid_output=raw_output,
        )
    try:
        model = output_model.model_validate(raw_output)
    except ValidationError as exc:
        raise V2StructuredLLMError(
            "structured_output_schema_invalid",
            str(exc),
            invalid_output=raw_output,
            validation_error_paths=[
                ".".join(str(part) for part in error.get("loc", ())) for error in exc.errors()
            ],
        ) from exc
    if quality_validator is not None:
        try:
            quality_validator(model)
        except Exception as exc:
            code = getattr(exc, "code", "structured_output_quality_failed")
            raise V2StructuredLLMError(
                "structured_output_quality_failed",
                str(exc),
                invalid_output=raw_output,
                quality_error_code=str(code),
                quality_error_message=str(exc),
                quality_error_details=getattr(exc, "repair_details", None),
            ) from exc
    return model


def _repair_payload(
    *,
    contract_name: str,
    output_model: type[BaseModel],
    original_payload: Any,
    invalid_output: Any,
    error: V2StructuredLLMError,
) -> dict[str, Any]:
    try:
        render_result = V2HighRiskPromptRenderer().render(
            prompt_id="v2.repair.structured_generation.v1",
            context={"contract_name": contract_name},
            identity={"path_kind": "repair"},
        )
    except V2HighRiskPromptRenderError as exc:
        raise V2StructuredLLMError(
            exc.code,
            str(exc),
            quality_error_details=exc.metadata,
        ) from exc
    prompt_lineage = V2PromptRegistry().lineage_for_render(render_result).model_dump(mode="json")
    sanitized, _warnings = sanitize_context_for_llm_text_with_warnings(
        {
            "repair": True,
            "instruction": render_result.prompt_text,
            "prompt_registry_ref": render_result.prompt_registry_ref.model_dump(mode="json"),
            "prompt_lineage": prompt_lineage,
            "contract_name": contract_name,
            "json_schema": output_model.model_json_schema(),
            "original_request": original_payload,
            "invalid_output": invalid_output,
            "validation_error_paths": error.validation_error_paths,
            "quality_error_code": error.quality_error_code,
            "quality_error_message": error.quality_error_message,
            "quality_repair_context": error.quality_error_details,
            "error_code": error.code,
            "error_message": str(error),
        }
    )
    return sanitized


def _extract_message_content(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except Exception as exc:  # noqa: BLE001 - SDK response shape is external.
        raise V2StructuredLLMError(
            "structured_llm_call_failed",
            "LLM response did not include choices[0].message.content.",
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise V2StructuredLLMError(
            "structured_output_invalid_json",
            "Structured LLM output was empty.",
            invalid_output=content,
        )
    return content


def _with_warnings(model: TModel, warnings: list[dict[str, Any]]) -> TModel:
    if not warnings or not hasattr(model, "warnings"):
        return model
    existing = getattr(model, "warnings", [])
    return model.model_copy(update={"warnings": [*existing, *warnings]})


def _is_json_schema_rejection(exc: Exception) -> bool:
    if isinstance(exc, V2StructuredLLMError):
        return exc.code == "structured_output_json_schema_unsupported"
    text = str(exc).lower()
    return "json_schema" in text or (
        "response_format" in text
        and any(term in text for term in ("unsupported", "not supported", "invalid"))
    )
