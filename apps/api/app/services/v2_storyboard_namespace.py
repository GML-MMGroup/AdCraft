from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from app.schemas.workflow_v2 import (
    V2ReferenceAsset,
    V2ReferenceBundle,
    WorkflowItemV2,
    WorkflowSlotV2,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text


STORYBOARD_NAMESPACE_ERROR_CODE = "v2_storyboard_namespace_violation"
STORYBOARD_NAMESPACE_STAGE = "storyboard_detail_quality"


class V2StoryboardNamespaceError(RuntimeError):
    def __init__(
        self,
        *,
        shot_id: str,
        slot_id: str,
        violations: list[dict[str, Any]],
    ) -> None:
        super().__init__("Storyboard data does not belong to the current shot namespace.")
        self.code = STORYBOARD_NAMESPACE_ERROR_CODE
        self.metadata = sanitize_context_for_llm_text(
            {
                "error_code": self.code,
                "stage": STORYBOARD_NAMESPACE_STAGE,
                "shot_id": shot_id,
                "slot_id": slot_id,
                "violations": violations,
            }
        )


def validate_storyboard_slot_namespace(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    bundle: V2ReferenceBundle,
    *,
    allowed_reference_item_ids: Sequence[str] | None = None,
) -> None:
    if item.item_type != "shot":
        return
    shot_id = item.shot_id or item.item_id
    violations = [
        *_detail_prompt_violations(item, shot_id),
        *_slot_ownership_violations(item, slot, shot_id),
        *_reference_ownership_violations(
            item,
            slot,
            bundle,
            shot_id,
            allowed_reference_item_ids=allowed_reference_item_ids,
        ),
    ]
    if violations:
        raise V2StoryboardNamespaceError(
            shot_id=shot_id,
            slot_id=slot.slot_id,
            violations=violations,
        )


def _detail_prompt_violations(
    item: WorkflowItemV2,
    shot_id: str,
) -> list[dict[str, Any]]:
    details = item.detail_prompts
    if not isinstance(details, dict):
        return []
    violations: list[dict[str, Any]] = []
    persisted_shot_id = str(details.get("shot_id") or "").strip()
    if persisted_shot_id and persisted_shot_id != shot_id:
        violations.append(_violation("$.item.detail_prompts.shot_id", "current_shot_mismatch"))
    persisted_shot_index = details.get("shot_index")
    if persisted_shot_index is not None and persisted_shot_index != item.shot_index:
        violations.append(_violation("$.item.detail_prompts.shot_index", "current_shot_mismatch"))
    expected_slot_ids = [f"{shot_id}:shot_cell_{index}" for index in range(1, 5)]
    required_slot_ids = details.get("required_shot_cell_slot_ids")
    if required_slot_ids != expected_slot_ids:
        violations.append(
            _violation(
                "$.item.detail_prompts.required_shot_cell_slot_ids",
                "current_shot_cells_required",
            )
        )
    return violations


def _slot_ownership_violations(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    shot_id: str,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if slot.item_id != item.item_id or not slot.slot_id.startswith(f"{shot_id}:"):
        violations.append(_violation("$.slot.slot_id", "slot_not_owned_by_current_shot"))
    return violations


def _reference_ownership_violations(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    bundle: V2ReferenceBundle,
    shot_id: str,
    *,
    allowed_reference_item_ids: Sequence[str] | None,
) -> list[dict[str, Any]]:
    if slot.slot_type == "shot_video_segment":
        expected_slot_ids = {f"{shot_id}:shot_cell_{index}" for index in range(1, 5)}
        cell_assets = [
            asset
            for asset in bundle.implicit_reference_assets
            if asset.source_relation == "same_shot_cell"
        ]
        actual_slot_ids = {str(asset.slot_id or "") for asset in cell_assets}
        invalid_assets = [
            asset
            for asset in bundle.provider_reference_assets
            if not asset.slot_id or asset.slot_id not in expected_slot_ids
        ]
        violations: list[dict[str, Any]] = []
        if actual_slot_ids != expected_slot_ids or len(cell_assets) != 4:
            violations.append(
                _violation(
                    "$.reference_bundle.implicit_reference_assets",
                    "four_current_shot_cell_assets_required",
                    fingerprints=[_asset_fingerprint(asset) for asset in cell_assets],
                )
            )
        if invalid_assets:
            violations.append(
                _violation(
                    "$.reference_bundle.provider_reference_assets",
                    "provider_reference_not_owned_by_current_shot",
                    fingerprints=[_asset_fingerprint(asset) for asset in invalid_assets],
                )
            )
        return violations

    if not slot.slot_type.startswith("shot_cell_"):
        return []
    allowed_item_ids = set(allowed_reference_item_ids or item.reference_item_ids)
    invalid_assets = [
        asset
        for asset in bundle.implicit_reference_assets
        if asset.source_relation == "storyboard_hard_dependency"
        and _asset_owner_item_id(asset) not in allowed_item_ids
    ]
    if not invalid_assets:
        return []
    return [
        _violation(
            "$.reference_bundle.implicit_reference_assets",
            "reference_asset_not_owned_by_current_script_shot",
            fingerprints=[_asset_fingerprint(asset) for asset in invalid_assets],
        )
    ]


def _asset_owner_item_id(asset: V2ReferenceAsset) -> str:
    slot_id = str(asset.slot_id or "")
    return slot_id.split(":", 1)[0] if ":" in slot_id else ""


def _asset_fingerprint(asset: V2ReferenceAsset) -> str:
    return _fingerprint(f"{asset.asset_id}:{asset.version_id}:{asset.slot_id or ''}")


def _violation(
    path: str,
    reason: str,
    *,
    fingerprints: list[str] | None = None,
) -> dict[str, Any]:
    violation: dict[str, Any] = {"path": path, "reason": reason}
    if fingerprints:
        violation["fingerprints"] = fingerprints
    return violation


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
