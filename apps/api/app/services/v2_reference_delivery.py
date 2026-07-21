from __future__ import annotations

from typing import Any

from app.schemas.workflow_v2_provider_prompt_contracts import V2ReferenceDeliveryAudit
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_provider_references import V2ReferenceAdaptation


def reference_delivery_audit_from_adaptation(
    adaptation: V2ReferenceAdaptation,
) -> dict[str, Any]:
    capability = adaptation.provider_capability_snapshot
    drop_reasons = _drop_reasons(adaptation)
    warnings = _warnings(adaptation, capability)
    audit = V2ReferenceDeliveryAudit(
        requested_reference_asset_ids=list(adaptation.requested_reference_asset_ids),
        submitted_reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
        dropped_reference_asset_ids=list(adaptation.dropped_reference_asset_ids),
        drop_reasons=drop_reasons,
        provider_supports_image_reference=_optional_bool(capability, "supports_image_reference"),
        provider_supports_video_reference=_optional_bool(capability, "supports_video_reference"),
        provider_supports_audio_reference=_optional_bool(capability, "supports_audio_reference"),
        provider_reference_confidence=str(capability.get("reference_confidence") or "unknown"),
        warnings=warnings,
    )
    return sanitize_context_for_llm_text(audit.model_dump(mode="json"))


def attach_reference_delivery_audit(
    payload: dict[str, Any],
    adaptation: V2ReferenceAdaptation,
) -> dict[str, Any]:
    return {
        **payload,
        "reference_delivery_audit": reference_delivery_audit_from_adaptation(adaptation),
    }


def _drop_reasons(adaptation: V2ReferenceAdaptation) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for warning in adaptation.reference_usage_warnings:
        asset_id = str(warning.get("asset_id") or "").strip()
        if not asset_id:
            continue
        reasons.setdefault(asset_id, str(warning.get("code") or "provider_reference_dropped"))
    for asset_id in adaptation.dropped_reference_asset_ids:
        reasons.setdefault(asset_id, "provider_reference_dropped")
    return reasons


def _warnings(
    adaptation: V2ReferenceAdaptation,
    capability: dict[str, Any],
) -> list[str]:
    warnings = [
        str(warning.get("code"))
        for warning in adaptation.reference_usage_warnings
        if str(warning.get("code") or "")
    ]
    if adaptation.dropped_reference_asset_ids:
        warnings.append("reference_dropped")
    if capability.get("reference_confidence") == "weak":
        warnings.append("provider_reference_support_weak")
    return list(dict.fromkeys(warnings))


def _optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None
