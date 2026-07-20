from typing import Any

from app.schemas.asset_library import ProviderCapability, ReferencePolicyResult
from app.services.canonical_assets import canonical_media_type, normalize_canonical_asset
from app.services.provider_capabilities import get_provider_capability
from app.services.provider_reference_adapter import build_provider_reference_plan

REFERENCE_MODES = {"best_effort", "strict"}
DEFAULT_REFERENCE_MODE = "strict"


def build_reference_policy(
    references: list[dict[str, Any]],
    *,
    node_type: str,
    provider: str,
    request_reference_mode: str = DEFAULT_REFERENCE_MODE,
    capability: ProviderCapability | None = None,
) -> ReferencePolicyResult:
    capability = capability or get_provider_capability(provider, node_type)
    effective_mode = _effective_policy_mode(references, request_reference_mode)
    plan = build_provider_reference_plan(
        references,
        node_type=node_type,
        media_type=capability.media_type or _media_type_for_node(node_type),
        provider=provider,
        request_reference_mode=request_reference_mode,
        capability=capability,
    )
    return ReferencePolicyResult(
        reference_mode=effective_mode,
        provider=provider,
        accepted_assets=plan.accepted_reference_assets,
        prompt_only_assets=plan.prompt_only_reference_assets,
        rejected_assets=plan.rejected_reference_assets,
        warnings=plan.warnings,
        errors=plan.errors,
        reference_plan=plan.model_dump(mode="json"),
    )


def _media_type_for_node(node_type: str) -> str:
    if node_type in {
        "product-generation",
        "character-generation",
        "scene-generation",
        "storyboard",
    }:
        return "image"
    if node_type == "storyboard-video-generation":
        return "video"
    if node_type == "bgm":
        return "audio"
    return ""


def _supported_reference_candidates(
    candidates: list[dict[str, Any]],
    *,
    capability: ProviderCapability,
    provider: str,
    request_reference_mode: str,
    prompt_only: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    supported_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_mode = _asset_reference_mode(candidate, request_reference_mode)
        support_errors = _support_errors(candidate, capability, provider)
        if not support_errors:
            supported_candidates.append(candidate)
            continue
        if candidate_mode == "strict":
            errors.extend(support_errors)
        elif _has_best_effort_blocking_support_error(support_errors):
            prompt_only.append(candidate)
            warnings.extend(_support_warnings(candidate, capability, provider, support_errors))
        else:
            supported_candidates.append(candidate)
            warnings.extend(_support_warnings(candidate, capability, provider, support_errors))
    return supported_candidates


def _apply_reference_capacity_policy(
    supported_candidates: list[dict[str, Any]],
    *,
    capability: ProviderCapability,
    provider: str,
    request_reference_mode: str,
    accepted: list[dict[str, Any]],
    prompt_only: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    max_assets = max(capability.max_reference_assets, 0)
    if max_assets == 0:
        _degrade_all_reference_candidates(
            supported_candidates,
            provider=provider,
            request_reference_mode=request_reference_mode,
            prompt_only=prompt_only,
            warnings=warnings,
            errors=errors,
        )
        return
    _accept_reference_candidates_with_limit(
        supported_candidates,
        max_assets=max_assets,
        provider=provider,
        request_reference_mode=request_reference_mode,
        accepted=accepted,
        prompt_only=prompt_only,
        warnings=warnings,
        errors=errors,
    )


def _degrade_all_reference_candidates(
    candidates: list[dict[str, Any]],
    *,
    provider: str,
    request_reference_mode: str,
    prompt_only: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    for candidate in candidates:
        if _asset_reference_mode(candidate, request_reference_mode) == "strict":
            errors.append(
                _policy_issue(
                    "strict_reference_not_supported",
                    candidate,
                    provider,
                    "Provider does not support reference assets for this node.",
                )
            )
        else:
            prompt_only.append(candidate)
            warnings.append(
                _policy_issue(
                    "provider_reference_degraded",
                    candidate,
                    provider,
                    "Reference asset is used as prompt context because provider does not support references.",
                )
            )


def _accept_reference_candidates_with_limit(
    candidates: list[dict[str, Any]],
    *,
    max_assets: int,
    provider: str,
    request_reference_mode: str,
    accepted: list[dict[str, Any]],
    prompt_only: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    prioritized = _primary_first(candidates)
    accepted.extend(prioritized[:max_assets])
    for candidate in prioritized[max_assets:]:
        if _asset_reference_mode(candidate, request_reference_mode) == "strict":
            errors.append(
                _policy_issue(
                    "strict_reference_asset_limit_exceeded",
                    candidate,
                    provider,
                    "Reference asset count exceeds provider capability.",
                )
            )
        else:
            prompt_only.append(candidate)
            warnings.append(
                _policy_issue(
                    "reference_asset_limit_degraded",
                    candidate,
                    provider,
                    "Reference asset exceeds provider limit and is used as prompt context.",
                )
            )


def policy_error_code(policy: ReferencePolicyResult | dict[str, Any]) -> str:
    errors = _policy_errors(policy)
    if not errors:
        return ""
    return str(errors[0].get("code") or "strict_reference_not_supported")


def policy_error_message(policy: ReferencePolicyResult | dict[str, Any]) -> str:
    codes = [str(error.get("code")) for error in _policy_errors(policy) if error.get("code")]
    return ", ".join(dict.fromkeys(codes)) or "strict_reference_not_supported"


def _policy_errors(policy: ReferencePolicyResult | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(policy, ReferencePolicyResult):
        return policy.errors
    errors = policy.get("errors") if isinstance(policy, dict) else []
    return (
        [error for error in errors if isinstance(error, dict)] if isinstance(errors, list) else []
    )


def _effective_policy_mode(references: list[dict[str, Any]], request_mode: str) -> str:
    modes = [
        str(reference.get("reference_mode") or "").strip()
        for reference in references
        if isinstance(reference, dict)
    ]
    if "strict" in modes:
        return "strict"
    normalized_request_mode = (
        request_mode if request_mode in REFERENCE_MODES else DEFAULT_REFERENCE_MODE
    )
    if normalized_request_mode == "strict":
        return "strict"
    return "best_effort"


def _reference_asset_candidates(
    references: list[dict[str, Any]],
    request_reference_mode: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for reference_index, reference in enumerate(references):
        if not isinstance(reference, dict):
            continue
        reference_mode = _normalized_reference_mode(
            str(reference.get("reference_mode") or request_reference_mode or DEFAULT_REFERENCE_MODE)
        )
        for asset_index, asset in enumerate(reference.get("assets", [])):
            if not isinstance(asset, dict):
                continue
            candidate = {
                **asset,
                "entity_id": reference.get("entity_id") or asset.get("entity_id"),
                "entity_type": reference.get("entity_type"),
                "display_name": reference.get("display_name"),
                "role": reference.get("role"),
                "use_as_prompt": bool(reference.get("use_as_prompt", True)),
                "lock_identity": bool(reference.get("lock_identity", False)),
                "allow_style_transfer": bool(reference.get("allow_style_transfer", False)),
                "is_primary": reference.get("is_primary"),
                "reference_mode": reference_mode,
                "_reference_index": reference_index,
                "_asset_index": asset_index,
            }
            normalized_candidate = normalize_canonical_asset(
                candidate,
                role=str(reference.get("role") or asset.get("role") or ""),
                entity_type=str(reference.get("entity_type") or asset.get("entity_type") or ""),
            )
            if asset.get("semantic_type"):
                normalized_candidate["semantic_type"] = asset.get("semantic_type")
            candidates.append(_public_candidate(normalized_candidate))
    if len(candidates) == 1:
        candidates[0]["is_primary"] = True
    return candidates


def _support_errors(
    asset: dict[str, Any],
    capability: ProviderCapability,
    provider: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not _media_type_supported(asset, capability):
        errors.append(
            _policy_issue(
                _unsupported_reference_code(asset),
                asset,
                provider,
                "Provider does not support this reference media type.",
            )
        )
    semantic_type = str(asset.get("semantic_type") or "")
    if (
        _semantic_capability_required(asset)
        and capability.supported_reference_semantic_types
        and semantic_type
        and semantic_type not in capability.supported_reference_semantic_types
    ):
        errors.append(
            _policy_issue(
                _unsupported_reference_code(asset),
                asset,
                provider,
                "Provider does not support this reference semantic type.",
            )
        )
    if asset.get("lock_identity") and not capability.supports_identity_lock:
        errors.append(
            _policy_issue(
                "identity_lock_not_supported",
                asset,
                provider,
                "Provider does not support strict identity lock.",
            )
        )
    if _is_style_reference(asset) and not capability.supports_style_reference:
        errors.append(
            _policy_issue(
                "style_reference_not_supported",
                asset,
                provider,
                "Provider does not support style reference constraints.",
            )
        )
    return errors


def _unsupported_reference_code(asset: dict[str, Any]) -> str:
    if asset.get("role") == "product_reference":
        return "product_reference_provider_unsupported"
    return "strict_reference_not_supported"


def _support_warnings(
    asset: dict[str, Any],
    capability: ProviderCapability,
    provider: str,
    support_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    error_codes = {str(error.get("code") or "") for error in support_errors}
    if (
        "strict_reference_not_supported" in error_codes
        or "provider_reference_type_unsupported" in error_codes
        or "product_reference_provider_unsupported" in error_codes
    ):
        warnings.append(
            _policy_issue(
                "provider_reference_degraded",
                asset,
                provider,
                "Reference asset is used as prompt context because provider does not support this reference type.",
            )
        )
    if "identity_lock_not_supported" in error_codes:
        warnings.append(
            _policy_issue(
                "identity_lock_not_supported",
                asset,
                provider,
                "Provider does not support identity lock; identity can only be encouraged through prompt context.",
            )
        )
    if "style_reference_not_supported" in error_codes:
        warnings.append(
            _policy_issue(
                "style_reference_not_supported",
                asset,
                provider,
                "Provider does not support style reference constraints; style remains prompt-only.",
            )
        )
    if not warnings and capability.max_reference_assets == 0:
        warnings.append(
            _policy_issue(
                "provider_reference_degraded",
                asset,
                provider,
                "Reference asset is used as prompt context.",
            )
        )
    return warnings


def _has_best_effort_blocking_support_error(support_errors: list[dict[str, Any]]) -> bool:
    codes = {str(error.get("code") or "") for error in support_errors}
    return bool(
        codes
        & {
            "strict_reference_not_supported",
            "provider_reference_type_unsupported",
            "product_reference_provider_unsupported",
            "style_reference_not_supported",
        }
    )


def _validate_primary_conflicts(
    candidates: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    primary_by_role: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        if candidate.get("is_primary") is True:
            primary_by_role.setdefault(str(candidate.get("role") or ""), []).append(candidate)
    for role, primary_assets in primary_by_role.items():
        if len(primary_assets) <= 1:
            continue
        for asset in primary_assets:
            errors.append(
                _policy_issue(
                    "primary_reference_conflict",
                    asset,
                    str(asset.get("provider") or ""),
                    f"Multiple primary references were selected for role {role}.",
                )
            )


def _assign_primary(
    candidates: list[dict[str, Any]],
    capability: ProviderCapability,
    effective_mode: str,
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    if not candidates:
        return
    if len(candidates) == 1:
        candidates[0]["is_primary"] = True
        return
    if capability.supports_multi_image_reference and capability.max_reference_assets > 1:
        return
    if any(candidate.get("is_primary") is True for candidate in candidates):
        return
    if effective_mode == "strict":
        for candidate in candidates:
            errors.append(
                _policy_issue(
                    "primary_reference_required",
                    candidate,
                    capability.provider,
                    "Provider supports only one reference; select a primary reference.",
                )
            )
        return
    candidates[0]["is_primary"] = True
    warnings.append(
        _policy_issue(
            "primary_reference_required",
            candidates[0],
            capability.provider,
            "Provider supports one reference; first compatible reference was selected as primary.",
        )
    )


def _media_type_supported(asset: dict[str, Any], capability: ProviderCapability) -> bool:
    asset_type = canonical_media_type(asset)
    if asset_type == "image":
        return capability.supports_image_reference
    if asset_type == "video":
        return capability.supports_video_reference
    if asset_type == "audio":
        return capability.supports_audio_reference
    return False


def _is_style_reference(asset: dict[str, Any]) -> bool:
    return (
        str(asset.get("role") or "") == "style_reference"
        or str(asset.get("semantic_type") or "") == "style_reference"
        or bool(asset.get("allow_style_transfer"))
    )


def _semantic_capability_required(asset: dict[str, Any]) -> bool:
    role = str(asset.get("role") or "")
    if role in {
        "product_reference",
        "character_reference",
        "scene_reference",
        "style_reference",
        "storyboard_reference",
        "video_reference",
        "bgm_reference",
    }:
        return True
    return bool(asset.get("lock_identity") or asset.get("allow_style_transfer"))


def _asset_reference_mode(asset: dict[str, Any], request_reference_mode: str) -> str:
    return _normalized_reference_mode(
        str(asset.get("reference_mode") or request_reference_mode or DEFAULT_REFERENCE_MODE)
    )


def _normalized_reference_mode(value: str) -> str:
    return value if value in REFERENCE_MODES else DEFAULT_REFERENCE_MODE


def _primary_first(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        assets,
        key=lambda asset: (
            0 if asset.get("is_primary") is True else 1,
            int(asset.get("_reference_index") or 0),
            int(asset.get("_asset_index") or 0),
        ),
    )


def _policy_issue(
    code: str,
    asset: dict[str, Any],
    provider: str,
    message: str,
) -> dict[str, Any]:
    issue = {
        "code": code,
        "message": message,
        "asset_id": asset.get("asset_id"),
        "entity_id": asset.get("entity_id"),
        "role": asset.get("role"),
        "provider": provider,
    }
    return {key: value for key, value in issue.items() if value not in (None, "")}


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    public = dict(candidate)
    public.pop("_reference_index", None)
    public.pop("_asset_index", None)
    return public


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (
            str(issue.get("code") or ""),
            str(issue.get("asset_id") or ""),
            str(issue.get("role") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped
