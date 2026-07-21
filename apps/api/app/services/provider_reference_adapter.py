from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.asset_library import ProviderCapability
from app.services.canonical_assets import canonical_media_type, normalize_canonical_asset
from app.services.provider_capabilities import get_provider_capability


ReferenceOutcome = Literal[
    "accepted_reference",
    "transformed_reference",
    "prompt_only",
    "rejected_soft",
    "rejected_strict",
]


class ProviderReferencePlan(BaseModel):
    provider: str
    node_type: str
    media_type: str
    accepted_reference_assets: list[dict[str, Any]] = Field(default_factory=list)
    transformed_reference_assets: list[dict[str, Any]] = Field(default_factory=list)
    prompt_only_reference_assets: list[dict[str, Any]] = Field(default_factory=list)
    rejected_reference_assets: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


def build_provider_reference_plan(
    references: list[dict[str, Any]],
    *,
    node_type: str,
    media_type: str,
    provider: str,
    request_reference_mode: str = "strict",
    capability: ProviderCapability | None = None,
) -> ProviderReferencePlan:
    capability = capability or get_provider_capability(provider, node_type)
    candidates = _reference_candidates(references, request_reference_mode)
    accepted: list[dict[str, Any]] = []
    prompt_only: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    _validate_primary_conflicts(candidates, warnings, errors)
    _assign_primary(candidates, capability, request_reference_mode, warnings, errors)
    supported: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_errors = _candidate_support_errors(
            candidate,
            capability=capability,
            provider=provider,
            media_type=media_type,
        )
        if not candidate_errors:
            supported.append(candidate)
            continue
        if _should_hard_reject(candidate, candidate_errors, request_reference_mode):
            rejected.append(_with_outcome(candidate, "rejected_strict"))
            errors.extend(candidate_errors)
            continue
        prompt_only.append(_with_outcome(candidate, "prompt_only"))
        warnings.extend(_support_warnings(candidate, provider, candidate_errors))

    _apply_capacity(
        supported,
        capability=capability,
        provider=provider,
        request_reference_mode=request_reference_mode,
        accepted=accepted,
        prompt_only=prompt_only,
        rejected=rejected,
        warnings=warnings,
        errors=errors,
    )

    if errors:
        accepted = []
        prompt_only = [
            asset for asset in prompt_only if _reference_role(asset) == "general_reference"
        ]
    return ProviderReferencePlan(
        provider=provider,
        node_type=node_type,
        media_type=media_type,
        accepted_reference_assets=_dedupe_assets(accepted),
        transformed_reference_assets=[],
        prompt_only_reference_assets=_dedupe_assets(prompt_only),
        rejected_reference_assets=_dedupe_assets(rejected),
        warnings=_dedupe_issues(warnings),
        errors=_dedupe_issues(errors),
    )


def _reference_candidates(
    references: list[dict[str, Any]],
    request_reference_mode: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for reference_index, reference in enumerate(references):
        if not isinstance(reference, dict):
            continue
        assets = reference.get("assets")
        if not isinstance(assets, list):
            continue
        reference_mode = _normalized_reference_mode(
            str(reference.get("reference_mode") or request_reference_mode or "strict")
        )
        for asset_index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                continue
            role = str(reference.get("role") or asset.get("role") or "")
            candidate = normalize_canonical_asset(
                {
                    **asset,
                    "entity_id": reference.get("entity_id") or asset.get("entity_id"),
                    "entity_type": reference.get("entity_type") or asset.get("entity_type"),
                    "display_name": reference.get("display_name") or asset.get("display_name"),
                    "role": role,
                    "use_as_prompt": bool(reference.get("use_as_prompt", True)),
                    "lock_identity": bool(reference.get("lock_identity", False)),
                    "allow_style_transfer": bool(reference.get("allow_style_transfer", False)),
                    "is_primary": reference.get("is_primary"),
                    "reference_mode": reference_mode,
                },
                role=role,
                entity_type=str(reference.get("entity_type") or asset.get("entity_type") or ""),
            )
            if asset.get("semantic_type"):
                candidate["semantic_type"] = asset.get("semantic_type")
            candidate["_reference_index"] = reference_index
            candidate["_asset_index"] = asset_index
            candidates.append(candidate)
    if len(candidates) == 1:
        candidates[0]["is_primary"] = True
    return candidates


def _candidate_support_errors(
    asset: dict[str, Any],
    *,
    capability: ProviderCapability,
    provider: str,
    media_type: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    asset_media_type = canonical_media_type(asset)
    if asset_media_type and asset_media_type not in {media_type, capability.media_type}:
        errors.append(
            _issue(
                "provider_reference_type_unsupported",
                asset,
                provider,
                "Reference asset media type is incompatible with this provider request.",
            )
        )
        return errors
    if not _media_reference_supported(asset_media_type or media_type, capability):
        errors.append(
            _issue(
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
            _issue(
                _unsupported_reference_code(asset),
                asset,
                provider,
                "Provider does not support this reference semantic type.",
            )
        )
    if asset.get("lock_identity") and not capability.supports_identity_lock:
        errors.append(
            _issue(
                "identity_lock_not_supported",
                asset,
                provider,
                "Provider does not support strict identity lock.",
            )
        )
    if _is_style_reference(asset) and not capability.supports_style_reference:
        errors.append(
            _issue(
                "style_reference_not_supported",
                asset,
                provider,
                "Provider does not support style reference constraints.",
            )
        )
    return errors


def _apply_capacity(
    candidates: list[dict[str, Any]],
    *,
    capability: ProviderCapability,
    provider: str,
    request_reference_mode: str,
    accepted: list[dict[str, Any]],
    prompt_only: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    max_assets = max(capability.max_reference_assets, 0)
    if max_assets <= 0:
        for candidate in candidates:
            if _should_hard_reject(
                candidate,
                [
                    _issue(
                        _unsupported_reference_code(candidate),
                        candidate,
                        provider,
                        "Provider does not support reference assets for this node.",
                    )
                ],
                request_reference_mode,
            ):
                rejected.append(_with_outcome(candidate, "rejected_strict"))
                errors.append(
                    _issue(
                        _unsupported_reference_code(candidate),
                        candidate,
                        provider,
                        "Provider does not support reference assets for this node.",
                    )
                )
            else:
                prompt_only.append(_with_outcome(candidate, "prompt_only"))
                warnings.append(
                    _issue(
                        "provider_reference_degraded",
                        candidate,
                        provider,
                        "Reference asset is used as prompt context because provider does not support references.",
                    )
                )
        return
    prioritized = _primary_first(candidates)
    for candidate in prioritized[:max_assets]:
        accepted.append(_with_outcome(candidate, "accepted_reference"))
    for candidate in prioritized[max_assets:]:
        if (
            _reference_role(candidate) == "general_reference"
            or _asset_mode(candidate, request_reference_mode) != "strict"
        ):
            prompt_only.append(_with_outcome(candidate, "prompt_only"))
            warnings.append(
                _issue(
                    "reference_asset_limit_degraded",
                    candidate,
                    provider,
                    "Reference asset exceeds provider limit and is used as prompt context.",
                )
            )
        else:
            rejected.append(_with_outcome(candidate, "rejected_strict"))
            errors.append(
                _issue(
                    "strict_reference_asset_limit_exceeded",
                    candidate,
                    provider,
                    "Reference asset count exceeds provider capability.",
                )
            )


def _should_hard_reject(
    asset: dict[str, Any],
    errors: list[dict[str, Any]],
    request_reference_mode: str,
) -> bool:
    codes = {str(error.get("code") or "") for error in errors}
    role = _reference_role(asset)
    if "provider_reference_type_unsupported" in codes:
        return True
    if role == "general_reference":
        return False
    if role == "product_reference" and _asset_mode(asset, request_reference_mode) == "strict":
        return True
    if asset.get("lock_identity") and "identity_lock_not_supported" in codes:
        return _asset_mode(asset, request_reference_mode) == "strict"
    if _is_style_reference(asset) and "style_reference_not_supported" in codes:
        return _asset_mode(asset, request_reference_mode) == "strict"
    return _asset_mode(asset, request_reference_mode) == "strict"


def _support_warnings(
    asset: dict[str, Any],
    provider: str,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings = [
        _issue(
            "provider_reference_degraded",
            asset,
            provider,
            "Reference asset is used as prompt context because provider does not support this reference type.",
        )
    ]
    for error in errors:
        if error.get("code") in {
            "identity_lock_not_supported",
            "style_reference_not_supported",
        }:
            warnings.append(dict(error))
    return warnings


def _validate_primary_conflicts(
    candidates: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    del warnings
    by_role: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        if candidate.get("is_primary") is True:
            by_role.setdefault(_reference_role(candidate), []).append(candidate)
    for role, primary_assets in by_role.items():
        if len(primary_assets) <= 1:
            continue
        for asset in primary_assets:
            errors.append(
                _issue(
                    "primary_reference_conflict",
                    asset,
                    "",
                    f"Multiple primary references were selected for role {role}.",
                )
            )


def _assign_primary(
    candidates: list[dict[str, Any]],
    capability: ProviderCapability,
    request_reference_mode: str,
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
    if _normalized_reference_mode(request_reference_mode) == "strict":
        for candidate in candidates:
            errors.append(
                _issue(
                    "primary_reference_required",
                    candidate,
                    capability.provider,
                    "Provider supports only one reference; select a primary reference.",
                )
            )
        return
    candidates[0]["is_primary"] = True
    warnings.append(
        _issue(
            "primary_reference_required",
            candidates[0],
            capability.provider,
            "Provider supports one reference; first compatible reference was selected as primary.",
        )
    )


def _media_reference_supported(media_type: str, capability: ProviderCapability) -> bool:
    if media_type == "image":
        return capability.supports_image_reference
    if media_type == "video":
        return capability.supports_video_reference
    if media_type == "audio":
        return capability.supports_audio_reference
    return False


def _semantic_capability_required(asset: dict[str, Any]) -> bool:
    return _reference_role(asset) in {
        "product_reference",
        "character_reference",
        "scene_reference",
        "style_reference",
        "storyboard_reference",
        "video_reference",
        "bgm_reference",
    } or bool(asset.get("lock_identity") or asset.get("allow_style_transfer"))


def _unsupported_reference_code(asset: dict[str, Any]) -> str:
    return (
        "product_reference_provider_unsupported"
        if _reference_role(asset) == "product_reference"
        else "strict_reference_not_supported"
    )


def _is_style_reference(asset: dict[str, Any]) -> bool:
    return (
        _reference_role(asset) == "style_reference"
        or str(asset.get("semantic_type") or "") == "style_reference"
        or bool(asset.get("allow_style_transfer"))
    )


def _asset_mode(asset: dict[str, Any], request_reference_mode: str) -> str:
    return _normalized_reference_mode(
        str(asset.get("reference_mode") or request_reference_mode or "strict")
    )


def _normalized_reference_mode(value: str) -> str:
    return value if value in {"best_effort", "strict"} else "strict"


def _reference_role(asset: dict[str, Any]) -> str:
    return str(asset.get("role") or "general_reference")


def _primary_first(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        assets,
        key=lambda asset: (
            0 if asset.get("is_primary") is True else 1,
            int(asset.get("_reference_index") or 0),
            int(asset.get("_asset_index") or 0),
        ),
    )


def _with_outcome(asset: dict[str, Any], outcome: ReferenceOutcome) -> dict[str, Any]:
    public = dict(asset)
    public.pop("_reference_index", None)
    public.pop("_asset_index", None)
    public["reference_outcome"] = outcome
    return public


def _issue(code: str, asset: dict[str, Any], provider: str, message: str) -> dict[str, Any]:
    payload = {
        "code": code,
        "message": message,
        "asset_id": asset.get("asset_id"),
        "entity_id": asset.get("entity_id"),
        "role": asset.get("role"),
        "provider": provider,
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def _dedupe_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in assets:
        key = str(asset.get("asset_id") or asset.get("local_path") or asset.get("uri") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(asset)
    return deduped


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
