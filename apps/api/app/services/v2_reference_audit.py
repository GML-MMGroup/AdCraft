from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.schemas.workflow_v2 import (
    V2ReferenceAsset,
    V2ReferenceBundle,
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_reference_audit import (
    V2ReferenceAudit,
    V2ReferenceAuditValidationResult,
    V2ReferenceDropReason,
    V2ReferenceUsage,
)
from app.schemas.workflow_v2_specialist_ownership import (
    V2ProviderPromptCompilationResult,
    V2SlotPromptContext,
)
from app.services.agent_trace import utc_now
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_provider_references import V2ReferenceAdaptation
from app.services.v2_shot_reference_resolver import (
    V2ShotReferenceResolver,
    V2ShotReferenceResolverError,
)


class V2ReferenceAuditError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.payload = payload


class V2ReferenceAuditBuilder:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._asset_store = V2AssetStoreService(data_dir)
        self._shot_reference_resolver = V2ShotReferenceResolver(data_dir)

    def build_pre_provider_audit(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        reference_bundle: V2ReferenceBundle,
        generation_action: str,
    ) -> V2ReferenceAudit:
        explicit = _asset_ids(reference_bundle.explicit_reference_assets)
        implicit = _asset_ids(reference_bundle.implicit_reference_assets)
        dependency = self._dependency_reference_asset_ids(workflow, item, slot)
        required = self._required_reference_asset_ids(workflow, item, slot)
        requested = _ordered_unique(
            [
                *_asset_ids(reference_bundle.provider_reference_assets),
                *explicit,
                *implicit,
                *dependency,
                *required,
            ]
        )
        usage = self._reference_usage(
            workflow=workflow,
            item=item,
            slot=slot,
            reference_bundle=reference_bundle,
            dependency_reference_asset_ids=dependency,
            required_reference_asset_ids=required,
            requested_reference_asset_ids=requested,
        )
        warnings = [
            warning.model_dump(mode="json") for warning in reference_bundle.reference_warnings
        ]
        return V2ReferenceAudit(
            audit_id=f"refaudit_{uuid4().hex[:12]}",
            workflow_id=workflow.workflow_id,
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            media_type=slot.media_type,
            generation_action=generation_action,
            reference_policy=str(
                reference_bundle.audit.get("policy")
                or item.metadata.get("reference_mode")
                or workflow.metadata.get("reference_mode")
                or "best_effort"
            ),
            required_reference_asset_ids=required,
            explicit_reference_asset_ids=explicit,
            implicit_reference_asset_ids=implicit,
            dependency_reference_asset_ids=dependency,
            requested_reference_asset_ids=requested,
            reference_usage=usage,
            warnings=warnings,
            created_at=utc_now().isoformat(),
        )

    def attach_slot_context_lineage(
        self,
        audit: V2ReferenceAudit,
        slot_context: V2SlotPromptContext,
        provider_prompt_result: V2ProviderPromptCompilationResult,
    ) -> V2ReferenceAudit:
        slot_context_fingerprint = fingerprint_payload(
            _slot_context_fingerprint_payload(slot_context)
        )
        provider_prompt_fingerprint = fingerprint_payload(
            {
                "provider_prompt": provider_prompt_result.provider_prompt,
                "negative_prompt": provider_prompt_result.negative_prompt,
                "negative_constraints": provider_prompt_result.negative_constraints,
                "reference_asset_ids": provider_prompt_result.reference_asset_ids,
                "reference_version_ids": provider_prompt_result.reference_version_ids,
            }
        )
        allowed = _ordered_unique(slot_context.reference_asset_ids)
        forbidden = _ordered_unique(
            [
                *audit.forbidden_reference_asset_ids,
                *[
                    asset_id
                    for asset_id in audit.requested_reference_asset_ids
                    if asset_id not in set(allowed)
                ],
            ]
        )
        return audit.model_copy(
            update={
                "slot_context_id": slot_context_id(slot_context),
                "slot_context_fingerprint": slot_context_fingerprint,
                "provider_prompt_fingerprint": provider_prompt_fingerprint,
                "allowed_reference_asset_ids": allowed,
                "forbidden_reference_asset_ids": forbidden,
            },
            deep=True,
        )

    def attach_slot_context_lineage_from_payload(
        self,
        audit: V2ReferenceAudit,
        provider_payload: dict[str, Any],
    ) -> V2ReferenceAudit:
        lineage = provider_payload.get("slot_context_lineage")
        if not isinstance(lineage, dict):
            lineage = {}
        allowed = _ordered_unique(
            [
                str(asset_id)
                for asset_id in (
                    lineage.get("allowed_reference_asset_ids")
                    or provider_payload.get("allowed_reference_asset_ids")
                    or []
                )
                if str(asset_id)
            ]
        )
        forbidden = _ordered_unique(
            [
                *audit.forbidden_reference_asset_ids,
                *[
                    asset_id
                    for asset_id in audit.requested_reference_asset_ids
                    if allowed and asset_id not in set(allowed)
                ],
                *[
                    str(asset_id)
                    for asset_id in (
                        lineage.get("forbidden_reference_asset_ids")
                        or provider_payload.get("forbidden_reference_asset_ids")
                        or []
                    )
                    if str(asset_id)
                ],
            ]
        )
        return audit.model_copy(
            update={
                "slot_context_id": lineage.get("slot_context_id")
                or provider_payload.get("slot_context_id"),
                "slot_context_fingerprint": lineage.get("slot_context_fingerprint")
                or provider_payload.get("slot_context_fingerprint"),
                "provider_prompt_fingerprint": lineage.get("provider_prompt_fingerprint")
                or provider_payload.get("provider_prompt_fingerprint"),
                "allowed_reference_asset_ids": allowed,
                "forbidden_reference_asset_ids": forbidden,
            },
            deep=True,
        )

    def apply_provider_adaptation(
        self,
        audit: V2ReferenceAudit,
        adaptation: V2ReferenceAdaptation,
    ) -> V2ReferenceAudit:
        provider = str(adaptation.provider_capability_snapshot.get("provider") or "")
        drop_reasons = list(audit.drop_reasons)
        known_drop_ids = {reason.asset_id for reason in drop_reasons}
        required_ids = set(audit.required_reference_asset_ids)
        for warning in adaptation.reference_usage_warnings:
            asset_id = str(warning.get("asset_id") or "").strip()
            if not asset_id or asset_id in known_drop_ids:
                continue
            drop_reasons.append(
                V2ReferenceDropReason(
                    asset_id=asset_id,
                    reason_code=str(warning.get("code") or "provider_reference_dropped"),
                    message=str(
                        warning.get("reason") or warning.get("message") or "Reference was dropped."
                    ),
                    provider=provider or None,
                    capability_field=_capability_field_for_warning(warning),
                    required=asset_id in required_ids,
                )
            )
        dropped = _ordered_unique(adaptation.dropped_reference_asset_ids)
        forbidden = _ordered_unique([*audit.forbidden_reference_asset_ids, *dropped])
        return audit.model_copy(
            update={
                "requested_reference_asset_ids": _ordered_unique(
                    [
                        *audit.requested_reference_asset_ids,
                        *adaptation.requested_reference_asset_ids,
                    ]
                ),
                "submitted_reference_asset_ids": _ordered_unique(
                    adaptation.submitted_reference_asset_ids
                ),
                "dropped_reference_asset_ids": dropped,
                "drop_reasons": drop_reasons,
                "forbidden_reference_asset_ids": forbidden,
                "provider": provider or audit.provider,
                "provider_capability_snapshot": dict(adaptation.provider_capability_snapshot),
            },
            deep=True,
        )

    def audit_from_payload(self, payload: dict[str, Any]) -> V2ReferenceAudit | None:
        raw = payload.get("reference_audit")
        if not isinstance(raw, dict):
            return None
        return V2ReferenceAudit.model_validate(raw)

    def validate_provider_payload_matches_audit(
        self,
        audit: V2ReferenceAudit,
        provider_payload: dict[str, Any],
    ) -> None:
        payload_ids = _ordered_unique(
            [
                str(asset_id)
                for asset_id in provider_payload.get("reference_asset_ids", [])
                if str(asset_id)
            ]
        )
        submitted = _ordered_unique(audit.submitted_reference_asset_ids)
        if payload_ids != submitted:
            raise V2ReferenceAuditError(
                "reference_audit_provider_payload_mismatch",
                "Provider payload reference_asset_ids differ from reference audit submitted references.",
            )
        allowed = set(audit.allowed_reference_asset_ids)
        if allowed and any(asset_id not in allowed for asset_id in submitted):
            raise V2ReferenceAuditError(
                "reference_audit_submitted_reference_not_allowed",
                "Provider payload includes a reference outside the current slot context allowlist.",
            )
        forbidden = set(audit.forbidden_reference_asset_ids)
        if forbidden.intersection(submitted):
            raise V2ReferenceAuditError(
                "reference_audit_submitted_reference_not_allowed",
                "Provider payload includes a forbidden reference.",
            )
        usage_ids = {usage.asset_id for usage in audit.reference_usage}
        if any(asset_id not in usage_ids for asset_id in submitted):
            raise V2ReferenceAuditError(
                "reference_audit_missing",
                "Every submitted reference must have a reference usage entry.",
            )
        dropped = set(audit.dropped_reference_asset_ids)
        reason_ids = {reason.asset_id for reason in audit.drop_reasons}
        if any(asset_id not in reason_ids for asset_id in dropped):
            raise V2ReferenceAuditError(
                "reference_drop_reason_missing",
                "Every dropped reference must have a drop reason.",
            )
        requested = set(audit.requested_reference_asset_ids)
        required = set(audit.required_reference_asset_ids)
        if not required.issubset(requested):
            raise V2ReferenceAuditError(
                "required_reference_asset_missing",
                "Required references must be included in requested references.",
            )
        if required.intersection(dropped):
            raise V2ReferenceAuditError(
                "provider_reference_adaptation_failed",
                "Required references were dropped before provider submission.",
            )
        self.validate_reference_audit(audit)

    def validate_reference_audit(self, audit: V2ReferenceAudit) -> None:
        if not audit.audit_id:
            raise V2ReferenceAuditError("reference_audit_missing")
        unsafe_paths = _unsafe_payload_paths(audit.model_dump(mode="json"))
        if unsafe_paths:
            raise V2ReferenceAuditError(
                "reference_audit_payload_unsafe",
                f"Reference audit contains unsafe payload paths: {', '.join(unsafe_paths[:8])}",
            )

    def validation_result(self, audit: V2ReferenceAudit) -> V2ReferenceAuditValidationResult:
        try:
            self.validate_reference_audit(audit)
        except V2ReferenceAuditError as exc:
            return V2ReferenceAuditValidationResult(
                valid=False,
                error_code=exc.code,
                error_message=str(exc),
                violations=[str(exc)],
            )
        return V2ReferenceAuditValidationResult(valid=True)

    def sanitize_reference_audit(self, audit: V2ReferenceAudit) -> dict[str, Any]:
        payload = sanitize_context_for_llm_text(audit.model_dump(mode="json"))
        unsafe_paths = _unsafe_payload_paths(payload)
        if unsafe_paths:
            raise V2ReferenceAuditError(
                "reference_audit_payload_unsafe",
                f"Reference audit contains unsafe payload paths: {', '.join(unsafe_paths[:8])}",
            )
        return payload

    def _dependency_reference_asset_ids(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> list[str]:
        if slot.slot_type == "shot_video_segment":
            return _selected_assets_for_slot_types(item, _shot_cell_slot_types())
        if slot.slot_type.startswith("shot_cell_"):
            return self._resolved_shot_reference_asset_ids(workflow, item)
        if slot.slot_type == "final_video":
            return self._final_video_reference_asset_ids(workflow)
        ids: list[str] = []
        for dependency_slot_id in slot.dependency_slot_ids:
            dependency = _find_slot(workflow, dependency_slot_id)
            if dependency and dependency.selected_asset_id:
                ids.append(dependency.selected_asset_id)
        return _ordered_unique(ids)

    def _resolved_shot_reference_asset_ids(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
    ) -> list[str]:
        try:
            resolved = self._shot_reference_resolver.resolve(
                workflow,
                item,
                require_selected_assets=True,
            )
        except V2ShotReferenceResolverError as exc:
            raise V2ReferenceAuditError(exc.code, str(exc)) from exc
        return [reference.asset_id for reference in resolved.required_assets]

    def _required_reference_asset_ids(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> list[str]:
        if slot.slot_type in {
            "product_multi_view_grid",
            "character_three_view",
            "scene_multi_view_grid",
            "shot_video_segment",
            "final_video",
        } or slot.slot_type.startswith("shot_cell_"):
            return self._dependency_reference_asset_ids(workflow, item, slot)
        return []

    def _final_video_reference_asset_ids(self, workflow: WorkflowV2) -> list[str]:
        ids: list[str] = []
        storyboard = _node_by_id(workflow, "storyboard")
        if storyboard is not None:
            for item in sorted(_active_items(storyboard), key=lambda shot: shot.shot_index or 0):
                slot = _slot_by_type(item, "shot_video_segment")
                if slot and slot.selected_asset_id:
                    ids.append(slot.selected_asset_id)
        if workflow.audio_mode != "none":
            bgm = _find_slot_by_type(workflow, "bgm_audio")
            if bgm and bgm.selected_asset_id:
                ids.append(bgm.selected_asset_id)
        return _ordered_unique(ids)

    def _reference_usage(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        reference_bundle: V2ReferenceBundle,
        dependency_reference_asset_ids: list[str],
        required_reference_asset_ids: list[str],
        requested_reference_asset_ids: list[str],
    ) -> list[V2ReferenceUsage]:
        usages: list[V2ReferenceUsage] = []
        required = set(required_reference_asset_ids)
        explicit = set(_asset_ids(reference_bundle.explicit_reference_assets))
        implicit = set(_asset_ids(reference_bundle.implicit_reference_assets))
        dependency = set(dependency_reference_asset_ids)
        for asset_id in requested_reference_asset_ids:
            record = self._asset_store.find_asset_version(asset_id=asset_id)
            source = _usage_source(asset_id, explicit, implicit, dependency)
            usages.append(
                V2ReferenceUsage(
                    asset_id=asset_id,
                    usage_role=_usage_role(slot, record),
                    source=source,
                    required=asset_id in required,
                    reason=_usage_reason(slot, source, asset_id in required),
                    owner_node_id=record.node_id if record else None,
                    owner_item_id=record.item_id if record else None,
                    owner_slot_id=record.slot_id if record else None,
                )
            )
        return usages


def slot_context_id(context: V2SlotPromptContext) -> str:
    return f"{context.workflow_id}:{context.slot_id}:{fingerprint_payload(_slot_context_fingerprint_payload(context))[:12]}"


def fingerprint_payload(payload: Any) -> str:
    sanitized = sanitize_context_for_llm_text(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _slot_context_fingerprint_payload(context: V2SlotPromptContext) -> dict[str, Any]:
    payload = context.model_dump(mode="json")
    return sanitize_context_for_llm_text(payload)


def _asset_ids(assets: Iterable[V2ReferenceAsset]) -> list[str]:
    return _ordered_unique([asset.asset_id for asset in assets])


def _ordered_unique(values: Iterable[str]) -> list[str]:
    normalized = [value for value in (str(raw).strip() for raw in values) if value]
    return list(dict.fromkeys(normalized))


def _selected_assets_for_slot_types(
    item: WorkflowItemV2,
    slot_types: Iterable[str],
) -> list[str]:
    wanted = set(slot_types)
    return _ordered_unique(
        [
            slot.selected_asset_id
            for slot in item.slots
            if slot.slot_type in wanted and slot.selected_asset_id
        ]
    )


def _usage_source(
    asset_id: str,
    explicit: set[str],
    implicit: set[str],
    dependency: set[str],
) -> str:
    if asset_id in dependency:
        return "dependency_slot_selected_asset"
    if asset_id in explicit:
        return "explicit_slot_reference"
    if asset_id in implicit:
        return "implicit_companion_reference"
    return "asset_owner_relation"


def _usage_role(slot: WorkflowSlotV2, record: WorkflowAssetVersionV2 | None) -> str:
    semantic = str(record.semantic_type if record else "")
    if slot.slot_type == "shot_video_segment":
        return "shot_cell_keyframe"
    if slot.slot_type == "final_video":
        return "bgm_audio" if (record and record.media_type == "audio") else "composition_clip"
    if slot.slot_type == "bgm_audio":
        return "bgm_audio"
    if "product" in slot.slot_type or semantic.startswith("product"):
        return "product_identity"
    if "character" in slot.slot_type or semantic.startswith("character"):
        return "character_identity"
    if "scene" in slot.slot_type or semantic.startswith("scene"):
        return "scene_identity"
    if semantic == "style_reference":
        return "style_reference"
    if semantic == "shot_video_segment":
        return "video_segment"
    return "free_reference"


def _usage_reason(slot: WorkflowSlotV2, source: str, required: bool) -> str:
    if required:
        return f"{slot.slot_type} requires this generated dependency."
    return f"{slot.slot_type} uses this {source.replace('_', ' ')}."


def _capability_field_for_warning(warning: dict[str, Any]) -> str | None:
    code = str(warning.get("code") or "")
    if "type" in code:
        return "supported_reference_media_types"
    if "semantic" in code:
        return "supported_reference_semantic_types"
    if "limit" in code or "trimmed" in code:
        return "max_reference_assets"
    if "missing_file" in code:
        return "file_path"
    if "metadata" in code:
        return "asset_metadata"
    return None


def _unsafe_payload_paths(payload: Any, prefix: str = "$") -> list[str]:
    unsafe: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(term in lowered for term in ("api_key", "secret", "token", "password")):
                unsafe.append(f"{prefix}.{key_text}")
            if key_text in {
                "provider_prompt",
                "slot_prompt_context",
                "full_provider_prompt",
                "sibling_provider_prompt",
                "sibling_detail_prompt",
                "workflow_json",
                "node_json",
                "resolved_inputs",
            }:
                unsafe.append(f"{prefix}.{key_text}")
            unsafe.extend(_unsafe_payload_paths(value, f"{prefix}.{key_text}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            unsafe.extend(_unsafe_payload_paths(value, f"{prefix}[{index}]"))
    elif isinstance(payload, (bytes, bytearray)):
        unsafe.append(prefix)
    elif isinstance(payload, str):
        lowered = payload.lower()
        if any(
            marker in lowered
            for marker in (
                "data:image",
                "data:video",
                "data:audio",
                ";base64",
                "raw_bytes",
                "file_content",
                "access_token",
                "api_key",
            )
        ):
            unsafe.append(prefix)
        if len(payload) > 4096:
            unsafe.append(prefix)
    return unsafe


def _node_by_id(workflow: WorkflowV2, node_id: str):
    return next((node for node in workflow.nodes if node.node_id == node_id), None)


def _active_items(node) -> list[WorkflowItemV2]:
    return [item for item in node.items if item.lifecycle_state == "active"]


def _slot_by_type(item: WorkflowItemV2, slot_type: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in item.slots if slot.slot_type == slot_type), None)


def _find_slot(workflow: WorkflowV2, slot_id: str) -> WorkflowSlotV2 | None:
    for node in workflow.nodes:
        for item in _active_items(node):
            for slot in item.slots:
                if slot.slot_id == slot_id:
                    return slot
    return None


def _find_slot_by_type(workflow: WorkflowV2, slot_type: str) -> WorkflowSlotV2 | None:
    for node in workflow.nodes:
        for item in _active_items(node):
            slot = _slot_by_type(item, slot_type)
            if slot is not None:
                return slot
    return None


def _shot_cell_slot_types() -> list[str]:
    return [f"shot_cell_{index}" for index in range(1, 5)]
