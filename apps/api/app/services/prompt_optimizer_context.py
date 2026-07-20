from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.services.provider_capabilities import get_provider_capability, provider_for_node
from app.services.provider_identity_certification import (
    IdentityCertificationRegistry,
    model_id_for_provider,
)


@dataclass(frozen=True)
class PromptOptimizerContextSummaries:
    selected_provider: str | None
    provider_capability_summary: dict[str, Any]
    reference_policy_summary: dict[str, Any]
    identity_certification_summary: dict[str, Any]


def prompt_optimizer_context_summaries(
    *,
    settings: Settings,
    workflow_id: str,
    node_id: str,
    node_type: str,
    input_context: dict[str, Any],
    media_type: str | None,
    media_mode: str,
    request_provider: str | None = None,
    reference_mode: str = "strict",
    asset_references: list[dict[str, Any]] | None = None,
) -> PromptOptimizerContextSummaries:
    selected_provider = (
        request_provider
        or _context_selected_provider(input_context)
        or provider_for_node(node_type, media_mode=media_mode)
    )
    capability = _context_dict(
        input_context,
        "provider_capability_summary",
        "provider_capability",
    )
    if not capability and selected_provider:
        capability = get_provider_capability(
            selected_provider,
            node_type=node_type,
        ).model_dump(mode="json")

    reference_policy = _context_dict(
        input_context,
        "reference_policy_summary",
        "reference_policy",
    )
    if not reference_policy:
        reference_policy = _provider_strategy_candidate_value(
            input_context,
            selected_provider,
            "reference_policy",
        )

    identity = _context_dict(
        input_context,
        "identity_certification_summary",
        "identity_certification",
    )
    if not identity:
        identity = _provider_strategy_candidate_value(
            input_context,
            selected_provider,
            "identity_certification",
        )
    references = asset_references or []
    if not identity and selected_provider and references:
        identity = (
            IdentityCertificationRegistry(settings=settings)
            .lookup(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node_type,
                media_type=media_type or "",
                provider=selected_provider,
                model_id=_identity_model_id_for_optimizer(selected_provider, node_type, settings),
                reference_mode=reference_mode,
                asset_references=references,
            )
            .model_dump(mode="json")
        )

    return PromptOptimizerContextSummaries(
        selected_provider=selected_provider,
        provider_capability_summary=capability,
        reference_policy_summary=reference_policy,
        identity_certification_summary=identity,
    )


def _context_selected_provider(context: dict[str, Any]) -> str | None:
    value = context.get("selected_provider")
    if isinstance(value, str) and value.strip():
        return value
    strategy = context.get("provider_strategy")
    if isinstance(strategy, dict):
        for key in ("selected_provider", "initial_selected_provider"):
            value = strategy.get(key)
            if isinstance(value, str) and value.strip():
                return value
    policy = context.get("reference_policy")
    if isinstance(policy, dict):
        value = policy.get("provider")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _context_dict(context: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = context.get(key)
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _provider_strategy_candidate_value(
    context: dict[str, Any],
    selected_provider: str | None,
    key: str,
) -> dict[str, Any]:
    strategy = context.get("provider_strategy")
    if not isinstance(strategy, dict):
        return {}
    candidates = strategy.get("candidates")
    if not isinstance(candidates, list):
        return {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if selected_provider and candidate.get("provider") != selected_provider:
            continue
        value = candidate.get(key)
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _identity_model_id_for_optimizer(
    provider: str,
    node_type: str,
    settings: Settings,
) -> str:
    try:
        return model_id_for_provider(provider, settings)
    except ValueError:
        if node_type in {
            "product-generation",
            "character-generation",
            "scene-generation",
            "storyboard",
        }:
            return settings.image_generation_model if not settings.agno_mock_mode else "mock-image"
        if node_type == "storyboard-video-generation":
            return settings.video_generation_model if not settings.agno_mock_mode else "mock-video"
        if node_type == "bgm":
            if settings.agno_mock_mode:
                return "mock-bgm"
            return settings.bgm_model or "configured-bgm"
        return "unknown"
