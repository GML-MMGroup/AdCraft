from collections.abc import Callable
from pathlib import Path
import time
from typing import Any, Protocol

from pydantic import BaseModel

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    V2GenerationPlan,
    V2ProviderResult,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
    WorkflowV2Event,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_event_store import V2EventStore


V2_PROVIDER_RETRY_POLICY_ID = "v2_provider_recovery_retry_v1"
PROVIDER_RECOVERABLE_SAFETY_FAILURE = "provider_recoverable_safety_failure"
PROVIDER_RECOVERABLE_TIMEOUT = "provider_recoverable_timeout"
PROVIDER_RECOVERABLE_RATE_LIMIT = "provider_recoverable_rate_limit"
PROVIDER_RECOVERABLE_TEMPORARY_FAILURE = "provider_recoverable_temporary_failure"
PROVIDER_RETRY_EXHAUSTED = "provider_retry_exhausted"
_TRANSIENT_RETRY_BASE_DELAY_SECONDS = 0.5
_TRANSIENT_RETRY_MAX_DELAY_SECONDS = 2.0

RetryEventAppender = Callable[..., WorkflowV2Event]


class V2ProviderExecutorLike(Protocol):
    def execute(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        plan: V2GenerationPlan,
    ) -> V2ProviderResult: ...


class V2ProviderRecoveryContext(BaseModel):
    workflow_id: str
    node_id: str
    item_id: str
    slot_id: str
    slot_type: str
    media_type: str


class V2ProviderRecoveryDecision(BaseModel):
    recoverable: bool
    retry_allowed: bool
    reason_code: str | None
    provider_error_code: str | None
    provider_error_message: str | None
    max_attempts: int


class V2ProviderRetryMetadata(BaseModel):
    provider_retry_attempts: int
    provider_retry_policy: str = V2_PROVIDER_RETRY_POLICY_ID
    provider_recovery_used: bool = True
    last_provider_error_code: str | None = None
    last_provider_error_message: str | None = None
    final_provider_error_code: str | None = None
    final_provider_error_message: str | None = None


PROVIDER_RETRY_METADATA_KEYS = tuple(V2ProviderRetryMetadata.model_fields.keys())


class V2ProviderRecoveryPolicy:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def decide(
        self,
        result: V2ProviderResult,
        context: V2ProviderRecoveryContext,
        *,
        retry_attempts_used: int,
    ) -> V2ProviderRecoveryDecision:
        max_attempts = self._max_attempts(context.media_type)
        reason_code = self._recoverable_reason(result)
        retry_allowed = bool(reason_code) and (retry_attempts_used + 1) < max_attempts
        return V2ProviderRecoveryDecision(
            recoverable=bool(reason_code),
            retry_allowed=retry_allowed,
            reason_code=reason_code,
            provider_error_code=result.error_code,
            provider_error_message=result.error_message,
            max_attempts=max_attempts,
        )

    def _max_attempts(self, media_type: str) -> int:
        if media_type == "video":
            return max(1, int(self._settings.provider_max_attempts_video))
        if media_type == "audio":
            return max(1, int(self._settings.provider_max_attempts_audio))
        return max(1, int(self._settings.provider_max_attempts_image))

    def _recoverable_reason(self, result: V2ProviderResult) -> str | None:
        code = str(result.error_code or "").strip()
        message = str(result.error_message or "").strip()
        haystack = f"{code} {message}".lower()
        normalized_code = code.lower()
        if _is_terminal_provider_error(normalized_code, haystack):
            return None
        if normalized_code == "provider_timeout":
            return PROVIDER_RECOVERABLE_TIMEOUT
        if normalized_code == "provider_rate_limited":
            return PROVIDER_RECOVERABLE_RATE_LIMIT
        if normalized_code in {
            "provider_connection_reset",
            "provider_temporary_unavailable",
            "provider_5xx",
            "provider_server_error",
        }:
            return PROVIDER_RECOVERABLE_TEMPORARY_FAILURE
        if "outputimagesensitivecontentdetected" in normalized_code or (
            "sensitive" in haystack and "content" in haystack
        ):
            return PROVIDER_RECOVERABLE_SAFETY_FAILURE
        if any(term in haystack for term in ("timeout", "timed out", "deadline exceeded")):
            return PROVIDER_RECOVERABLE_TIMEOUT
        if any(
            term in haystack
            for term in ("rate limit", "rate_limit", "ratelimit", "too many requests", " 429")
        ):
            return PROVIDER_RECOVERABLE_RATE_LIMIT
        if any(
            term in haystack
            for term in (
                "temporary",
                "temporarily",
                "unavailable",
                "server error",
                "internal server",
                "connection reset",
                "upstream",
                " 500",
                " 502",
                " 503",
                " 504",
                "5xx",
            )
        ):
            return PROVIDER_RECOVERABLE_TEMPORARY_FAILURE
        return None


class V2ProviderRecoveryRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        data_dir: Path,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._policy = V2ProviderRecoveryPolicy(settings)
        self._event_store = V2EventStore(data_dir)
        self._sleep = sleep or time.sleep

    def execute(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        plan: V2GenerationPlan,
        executor: V2ProviderExecutorLike,
        append_event: RetryEventAppender | None = None,
    ) -> tuple[V2ProviderResult, V2GenerationPlan]:
        context = V2ProviderRecoveryContext(
            workflow_id=workflow.workflow_id,
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            media_type=str(slot.media_type),
        )
        current_plan = plan
        result = executor.execute(workflow, item, slot, current_plan)
        if result.status != "failed":
            return result, current_plan

        retry_attempts_used = 0
        while result.status == "failed":
            decision = self._policy.decide(
                result,
                context,
                retry_attempts_used=retry_attempts_used,
            )
            if not decision.recoverable:
                return result, current_plan
            if not decision.retry_allowed:
                exhausted = _retry_exhausted_result(
                    result,
                    decision=decision,
                    retry_attempts_used=retry_attempts_used,
                )
                _apply_retry_metadata_to_slot(slot, exhausted.metadata)
                self._append_retry_event(
                    "provider_retry_exhausted",
                    context,
                    decision,
                    attempt=retry_attempts_used,
                    append_event=append_event,
                )
                return exhausted, current_plan

            retry_attempts_used += 1
            retry_metadata = _retry_metadata(
                decision,
                retry_attempts_used=retry_attempts_used,
            )
            _apply_retry_metadata_to_slot(slot, retry_metadata)
            self._append_retry_event(
                "provider_retry_scheduled",
                context,
                decision,
                attempt=retry_attempts_used,
                append_event=append_event,
            )
            retry_plan = _retry_plan(current_plan, slot, decision)
            retry_delay = _provider_retry_delay_seconds(decision, retry_attempts_used)
            if retry_delay > 0:
                self._sleep(retry_delay)
            self._append_retry_event(
                "provider_retry_started",
                context,
                decision,
                attempt=retry_attempts_used,
                append_event=append_event,
            )
            retry_result = executor.execute(workflow, item, slot, retry_plan)
            if retry_result.status != "failed":
                metadata = {
                    **sanitize_context_for_llm_text(retry_result.metadata),
                    **retry_metadata,
                }
                retry_result = retry_result.model_copy(update={"metadata": metadata})
                _apply_retry_metadata_to_slot(slot, metadata)
                self._append_retry_event(
                    "provider_retry_succeeded",
                    context,
                    decision,
                    attempt=retry_attempts_used,
                    append_event=append_event,
                )
                return retry_result, retry_plan

            next_decision = self._policy.decide(
                retry_result,
                context,
                retry_attempts_used=retry_attempts_used,
            )
            if next_decision.retry_allowed:
                failed_metadata = _retry_metadata(
                    next_decision,
                    retry_attempts_used=retry_attempts_used,
                )
                _apply_retry_metadata_to_slot(slot, failed_metadata)
                self._append_retry_event(
                    "provider_retry_failed",
                    context,
                    next_decision,
                    attempt=retry_attempts_used,
                    append_event=append_event,
                )
                result = retry_result
                current_plan = retry_plan
                continue

            exhausted = _retry_exhausted_result(
                retry_result,
                decision=next_decision,
                retry_attempts_used=retry_attempts_used,
            )
            _apply_retry_metadata_to_slot(slot, exhausted.metadata)
            self._append_retry_event(
                "provider_retry_failed",
                context,
                next_decision,
                attempt=retry_attempts_used,
                append_event=append_event,
            )
            self._append_retry_event(
                "provider_retry_exhausted",
                context,
                next_decision,
                attempt=retry_attempts_used,
                append_event=append_event,
            )
            return exhausted, retry_plan

        return result, current_plan

    def _append_retry_event(
        self,
        event_type: str,
        context: V2ProviderRecoveryContext,
        decision: V2ProviderRecoveryDecision,
        *,
        attempt: int,
        append_event: RetryEventAppender | None,
    ) -> WorkflowV2Event:
        payload = {
            "attempt": attempt,
            "max_attempts": decision.max_attempts,
            "reason_code": decision.reason_code,
            "provider_error_code": decision.provider_error_code,
            "provider_error_message": decision.provider_error_message,
            "provider_retry_policy": V2_PROVIDER_RETRY_POLICY_ID,
            "node_id": context.node_id,
            "item_id": context.item_id,
            "slot_id": context.slot_id,
            "slot_type": context.slot_type,
            "media_type": context.media_type,
        }
        event_kwargs = {
            "node_id": context.node_id,
            "item_id": context.item_id,
            "slot_id": context.slot_id,
            "payload": sanitize_context_for_llm_text(payload),
        }
        if append_event is not None:
            return append_event(context.workflow_id, event_type, **event_kwargs)
        return self._event_store.append_event(context.workflow_id, event_type, **event_kwargs)


def _is_terminal_provider_error(normalized_code: str, haystack: str) -> bool:
    terminal_codes = {
        "provider_configuration_missing",
        "provider_config_missing",
        "media_configuration_missing",
        "provider_payload_invalid",
        "provider_prompt_payload_invalid",
        "v2_provider_prompt_empty",
        "v2_video_prompt_empty",
        "v2_provider_prompt_mismatch",
        "v2_legacy_prompt_field_used",
        "provider_reference_missing",
        "provider_reference_delivery_failed",
        "provider_reference_media_type_unsupported",
        "missing_selected_main_image",
        "asset_not_found",
        "unsupported_media_type",
        "v2_data_boundary_violation",
    }
    if normalized_code in terminal_codes:
        return True
    terminal_terms = (
        "missing api key",
        "api key",
        "credential",
        "missing endpoint",
        "base url",
        "configuration",
        "invalid payload",
        "missing input asset",
        "input asset missing",
        "reference missing",
        "unsupported media type",
        "unsupported v2 provider media type",
    )
    return any(term in haystack for term in terminal_terms)


def _provider_retry_delay_seconds(
    decision: V2ProviderRecoveryDecision,
    retry_attempts_used: int,
) -> float:
    if decision.reason_code not in {
        PROVIDER_RECOVERABLE_TIMEOUT,
        PROVIDER_RECOVERABLE_RATE_LIMIT,
        PROVIDER_RECOVERABLE_TEMPORARY_FAILURE,
    }:
        return 0.0
    exponent = max(0, retry_attempts_used - 1)
    return min(
        _TRANSIENT_RETRY_MAX_DELAY_SECONDS,
        _TRANSIENT_RETRY_BASE_DELAY_SECONDS * (2**exponent),
    )


def _retry_metadata(
    decision: V2ProviderRecoveryDecision,
    *,
    retry_attempts_used: int,
) -> dict[str, Any]:
    return V2ProviderRetryMetadata(
        provider_retry_attempts=retry_attempts_used,
        last_provider_error_code=decision.provider_error_code,
        last_provider_error_message=decision.provider_error_message,
    ).model_dump(mode="json", exclude_none=True)


def _retry_exhausted_result(
    result: V2ProviderResult,
    *,
    decision: V2ProviderRecoveryDecision,
    retry_attempts_used: int,
) -> V2ProviderResult:
    metadata = {
        **sanitize_context_for_llm_text(result.metadata),
        **_retry_metadata(decision, retry_attempts_used=retry_attempts_used),
    }
    metadata.update(
        V2ProviderRetryMetadata(
            provider_retry_attempts=retry_attempts_used,
            last_provider_error_code=decision.provider_error_code,
            last_provider_error_message=decision.provider_error_message,
            final_provider_error_code=decision.provider_error_code,
            final_provider_error_message=decision.provider_error_message,
        ).model_dump(mode="json", exclude_none=True)
    )
    return result.model_copy(
        update={
            "error_code": PROVIDER_RETRY_EXHAUSTED,
            "error_message": (
                "Provider generation failed after bounded recovery attempts. "
                f"Last provider error: {decision.provider_error_message or decision.provider_error_code}."
            ),
            "metadata": metadata,
        }
    )


def _apply_retry_metadata_to_slot(slot: WorkflowSlotV2, metadata: dict[str, Any]) -> None:
    slot.metadata.update(sanitize_context_for_llm_text(metadata))


def provider_retry_metadata_from_result(result: V2ProviderResult) -> dict[str, Any]:
    return {
        key: value
        for key in PROVIDER_RETRY_METADATA_KEYS
        if (value := result.metadata.get(key)) is not None
    }


def _retry_plan(
    plan: V2GenerationPlan,
    slot: WorkflowSlotV2,
    decision: V2ProviderRecoveryDecision,
) -> V2GenerationPlan:
    if decision.reason_code != PROVIDER_RECOVERABLE_SAFETY_FAILURE or slot.media_type != "image":
        return plan
    return _safety_rewrite_plan(plan, slot)


def _safety_rewrite_plan(plan: V2GenerationPlan, slot: WorkflowSlotV2) -> V2GenerationPlan:
    provider_payload = dict(plan.provider_payload)
    original_prompt = str(
        provider_payload.get("provider_prompt") or plan.materialized_prompt.provider_prompt or ""
    ).strip()
    rewritten_prompt = "\n\n".join(
        part for part in (original_prompt, _safety_overlay_for_slot(slot.slot_type)) if part
    )
    provider_payload.update(
        {
            "provider_prompt": rewritten_prompt,
            "provider_recovery": {
                "provider_retry_policy": V2_PROVIDER_RETRY_POLICY_ID,
                "rewrite": "safety_prompt_overlay",
                "slot_type": slot.slot_type,
            },
        }
    )
    materialized_prompt = plan.materialized_prompt.model_copy(
        update={"provider_prompt": rewritten_prompt},
        deep=True,
    )
    return plan.model_copy(
        update={
            "provider_payload": provider_payload,
            "materialized_prompt": materialized_prompt,
        },
        deep=True,
    )


def _safety_overlay_for_slot(slot_type: str) -> str:
    if slot_type == "character_main_image":
        return (
            "Provider recovery safety rewrite: create a safe commercial single full-body "
            "character image in one view, preserving the described character identity, "
            "with a neutral studio background, no unrelated products, and no unrelated "
            "environments."
        )
    if slot_type == "scene_main_image":
        return (
            "Provider recovery safety rewrite: create a safe commercial environment-only "
            "scene image, preserving the intended location and mood, without people or "
            "products unless they are explicitly required by the prompt."
        )
    if slot_type == "product_main_image":
        return (
            "Provider recovery safety rewrite: create a safe commercial product image, "
            "preserving product identity, packaging, logo placement, and silhouette; avoid "
            "unrelated people, hands, or props unless explicitly required by the prompt."
        )
    if slot_type.startswith("shot_cell_"):
        return (
            "Provider recovery safety rewrite: create a safe commercial storyboard cell, "
            "preserving this shot cell's intent, composition, and selected references, while "
            "avoiding unrelated or unsafe content."
        )
    return (
        "Provider recovery safety rewrite: create a safe commercial image that preserves "
        "the requested subject and slot intent while avoiding unrelated or unsafe content."
    )
