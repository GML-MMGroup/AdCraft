from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Literal, Mapping

V2LLMAttemptKind = Literal["initial", "repair"]
V2LLMProviderOption = bool | int


class V2LLMReasoningMode(str, Enum):
    DISABLED = "disabled"
    BOUNDED = "bounded"
    PROVIDER_DEFAULT = "provider_default"


@dataclass(frozen=True, slots=True)
class _StagePolicy:
    reasoning_mode: V2LLMReasoningMode
    thinking_budget: int
    timeout_seconds: int
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class V2ResolvedLLMCallPolicy:
    provider_id: str
    stage_name: str
    attempt_kind: V2LLMAttemptKind
    reasoning_mode: V2LLMReasoningMode
    thinking_budget: int
    timeout_seconds: int
    max_output_tokens: int
    sdk_max_retries: int
    max_transient_retries: int
    transient_retry_delay_seconds: float
    provider_request_options: Mapping[str, V2LLMProviderOption]


_STAGE_POLICIES: Mapping[str, _StagePolicy] = MappingProxyType(
    {
        "front_desk": _StagePolicy(V2LLMReasoningMode.DISABLED, 0, 45, 2_048),
        "intent_contract_planner": _StagePolicy(
            V2LLMReasoningMode.DISABLED,
            0,
            45,
            4_096,
        ),
        "script_writer": _StagePolicy(V2LLMReasoningMode.BOUNDED, 2_048, 90, 8_192),
        "expert_brief_planner": _StagePolicy(
            V2LLMReasoningMode.BOUNDED,
            2_048,
            90,
            8_192,
        ),
        "storyboard_detail": _StagePolicy(
            V2LLMReasoningMode.BOUNDED,
            2_048,
            90,
            8_192,
        ),
        "specialist_materializer": _StagePolicy(
            V2LLMReasoningMode.BOUNDED,
            1_024,
            75,
            4_096,
        ),
        "script_edit_normalization": _StagePolicy(
            V2LLMReasoningMode.DISABLED,
            0,
            45,
            4_096,
        ),
        "structured_repair": _StagePolicy(
            V2LLMReasoningMode.DISABLED,
            0,
            45,
            4_096,
        ),
        "agent_default": _StagePolicy(
            V2LLMReasoningMode.PROVIDER_DEFAULT,
            0,
            120,
            8_192,
        ),
    }
)


class V2LLMCallPolicyResolver:
    def __init__(self, *, transient_retry_delay_seconds: float = 2.0) -> None:
        if transient_retry_delay_seconds < 0:
            raise ValueError("Transient retry delay must be non-negative.")
        self._transient_retry_delay_seconds = transient_retry_delay_seconds

    def resolve(
        self,
        *,
        provider_id: str,
        stage_name: str,
        attempt_kind: V2LLMAttemptKind,
    ) -> V2ResolvedLLMCallPolicy:
        if attempt_kind not in {"initial", "repair"}:
            raise ValueError(f"Unsupported LLM attempt kind: {attempt_kind}")

        resolved_stage_name = (
            "structured_repair"
            if attempt_kind == "repair"
            else stage_name.strip()
            if stage_name.strip() in _STAGE_POLICIES
            else "agent_default"
        )
        stage_policy = _STAGE_POLICIES[resolved_stage_name]
        canonical_provider_id = _canonical_provider_id(provider_id)
        provider_options = _provider_request_options(
            provider_id=canonical_provider_id,
            stage_policy=stage_policy,
        )
        return V2ResolvedLLMCallPolicy(
            provider_id=canonical_provider_id,
            stage_name=resolved_stage_name,
            attempt_kind=attempt_kind,
            reasoning_mode=stage_policy.reasoning_mode,
            thinking_budget=stage_policy.thinking_budget,
            timeout_seconds=stage_policy.timeout_seconds,
            max_output_tokens=stage_policy.max_output_tokens,
            sdk_max_retries=0,
            max_transient_retries=1,
            transient_retry_delay_seconds=self._transient_retry_delay_seconds,
            provider_request_options=MappingProxyType(provider_options),
        )


def _canonical_provider_id(provider_id: str) -> str:
    canonical = provider_id.strip().casefold().replace("-", "_").replace(" ", "_")
    while "__" in canonical:
        canonical = canonical.replace("__", "_")
    return canonical or "openai_compatible"


def _provider_request_options(
    *,
    provider_id: str,
    stage_policy: _StagePolicy,
) -> dict[str, V2LLMProviderOption]:
    if provider_id != "siliconflow":
        return {}
    if stage_policy.reasoning_mode is V2LLMReasoningMode.DISABLED:
        return {"enable_thinking": False}
    if stage_policy.reasoning_mode is V2LLMReasoningMode.BOUNDED:
        return {
            "enable_thinking": True,
            "thinking_budget": stage_policy.thinking_budget,
        }
    return {}
