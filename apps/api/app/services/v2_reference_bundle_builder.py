from pathlib import Path
from typing import Any

from app.schemas.workflow_v2 import (
    V2ReferenceAsset,
    V2ReferenceBundle,
    V2ReferenceBundleTarget,
    V2ReferenceBundleTextContext,
    V2ReferenceWarning,
    WorkflowAssetRelationV2,
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_shot_reference_resolver import (
    V2ShotReferenceResolver,
    V2ShotReferenceResolverError,
)
from app.services.v2_workflow_assets import _display_name, _normalize_semantic_type
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime


class V2ReferenceBundleBuilder:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._asset_store = V2AssetStoreService(data_dir)
        self._authoring_runtime = create_workflow_authoring_runtime(data_dir)
        self._shot_reference_resolver = V2ShotReferenceResolver(data_dir)

    def build_reference_bundle(
        self,
        *,
        workflow_id: str,
        target_node_id: str,
        target_item_id: str | None,
        target_slot_id: str,
        generation_mode: str,
    ) -> V2ReferenceBundle:
        del target_node_id, target_item_id
        workflow = self._authoring_runtime.read_model.assemble(workflow_id)
        return self._build_from_workflow(
            workflow,
            target_slot_id=target_slot_id,
            generation_mode=generation_mode,
        )

    def _build_from_workflow(
        self,
        workflow: WorkflowV2,
        *,
        target_slot_id: str,
        generation_mode: str,
    ) -> V2ReferenceBundle:
        slot = _find_slot(workflow, target_slot_id)
        if slot is None:
            raise ValueError("slot_not_found")
        item = _find_item(workflow, slot.node_id, slot.item_id)
        if item is None:
            raise ValueError("item_not_found")
        explicit, explicit_warnings = self._explicit_assets(workflow, item, slot)
        implicit, implicit_warnings = self._implicit_assets(workflow, item, slot)
        ordered_assets = (
            [*implicit, *explicit]
            if item.item_type == "shot" and slot.slot_type.startswith("shot_cell_")
            else [*explicit, *implicit]
        )
        provider, provider_warnings = _provider_assets(slot, ordered_assets)
        llm_assets = [_llm_asset(asset) for asset in ordered_assets]
        return V2ReferenceBundle(
            workflow_id=workflow.workflow_id,
            target=V2ReferenceBundleTarget(
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                slot_type=slot.slot_type,
            ),
            text_context=_text_context(workflow, item, slot),
            explicit_reference_assets=explicit,
            implicit_reference_assets=implicit,
            provider_reference_assets=provider,
            llm_context_assets=llm_assets,
            reference_warnings=[*explicit_warnings, *implicit_warnings, *provider_warnings],
            audit={
                "policy": "best_effort",
                "bundle_version": 1,
                "generation_mode": generation_mode,
            },
        )

    def build_for_slot(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        *,
        generation_mode: str,
    ) -> V2ReferenceBundle:
        del item
        return self._build_from_workflow(
            workflow,
            target_slot_id=slot.slot_id,
            generation_mode=generation_mode,
        )

    def _explicit_assets(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> tuple[list[V2ReferenceAsset], list[V2ReferenceWarning]]:
        relations = [
            *self._asset_store.list_relations(
                target_workflow_id=workflow.workflow_id,
                target_slot_id=slot.slot_id,
                relation_type="reference_for_slot",
            ),
            *[
                relation
                for relation in self._asset_store.list_relations(
                    target_workflow_id=workflow.workflow_id,
                    relation_type="reference_for_item",
                )
                if relation.target_item_id == item.item_id
            ],
        ]
        assets: list[V2ReferenceAsset] = []
        warnings: list[V2ReferenceWarning] = []
        for relation in relations:
            asset, warning = self._asset_from_relation(relation, role=_role_from_relation(relation))
            if asset is not None:
                assets.append(asset)
            if warning is not None:
                warnings.append(warning)
        return _dedupe_assets(assets), warnings

    def _implicit_assets(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> tuple[list[V2ReferenceAsset], list[V2ReferenceWarning]]:
        assets: list[V2ReferenceAsset] = []
        warnings: list[V2ReferenceWarning] = []
        if item.item_type == "shot" and slot.slot_type.startswith("shot_cell_"):
            try:
                resolved = self._shot_reference_resolver.resolve(
                    workflow,
                    item,
                    require_selected_assets=False,
                )
            except V2ShotReferenceResolverError as exc:
                raise ValueError(exc.code) from exc
            for reference in resolved.required_assets:
                source_slot = _find_slot(workflow, reference.slot_id)
                if source_slot is None:
                    continue
                asset = self._asset_from_slot(
                    source_slot,
                    role=_role_for_slot(source_slot),
                    source_relation="storyboard_hard_dependency",
                )
                if asset is not None:
                    assets.append(asset)
            for reference in resolved.optional_assets:
                source_slot = _find_slot(workflow, reference.slot_id)
                if source_slot is None:
                    continue
                asset = self._asset_from_slot(
                    source_slot,
                    role=_role_for_slot(source_slot),
                    source_relation="companion_of",
                )
                if asset is not None:
                    assets.append(asset)
            warnings.extend(_soft_dependency_warnings(workflow))
        companion_slot_type = {
            "product_main_image": "product_multi_view_grid",
            "character_main_image": "character_three_view",
            "scene_main_image": "scene_multi_view_grid",
        }.get(slot.slot_type)
        if companion_slot_type:
            companion = _slot_by_type(item, companion_slot_type)
            if companion and companion.selected_asset_id:
                asset = self._asset_from_slot(
                    companion,
                    role=_role_for_slot(companion),
                    source_relation="companion_of",
                )
                if asset is not None:
                    assets.append(asset)
            else:
                warnings.append(
                    V2ReferenceWarning(
                        code="companion_reference_missing",
                        message=f"Selected companion asset is missing for {companion_slot_type}.",
                    )
                )
        if slot.slot_type in {
            "product_multi_view_grid",
            "character_three_view",
            "scene_multi_view_grid",
        }:
            for dependency_slot_id in slot.dependency_slot_ids:
                dependency = _find_slot(workflow, dependency_slot_id)
                if dependency and dependency.selected_asset_id:
                    asset = self._asset_from_slot(
                        dependency,
                        role=_role_for_slot(dependency),
                        source_relation="dependency_slot",
                    )
                    if asset is not None:
                        assets.append(asset)
        if slot.slot_type == "shot_video_segment":
            for cell_type in ("shot_cell_1", "shot_cell_2", "shot_cell_3", "shot_cell_4"):
                cell = _slot_by_type(item, cell_type)
                if cell and cell.selected_asset_id:
                    asset = self._asset_from_slot(
                        cell,
                        role="composition",
                        source_relation="same_shot_cell",
                    )
                    if asset is not None:
                        assets.append(asset)
                else:
                    warnings.append(
                        V2ReferenceWarning(
                            code="shot_cell_reference_missing",
                            message=f"Selected {cell_type} asset is missing.",
                        )
                    )
        if slot.slot_type == "final_video":
            for shot in _storyboard_items(workflow):
                video_slot = _slot_by_type(shot, "shot_video_segment")
                if video_slot and video_slot.selected_asset_id:
                    asset = self._asset_from_slot(
                        video_slot,
                        role="composition",
                        source_relation="selected_shot_video",
                    )
                    if asset is not None:
                        assets.append(asset)
            if workflow.audio_mode != "none":
                bgm_slot = next(
                    (
                        candidate
                        for candidate in _workflow_slots(workflow)
                        if candidate.slot_type == "bgm_audio"
                    ),
                    None,
                )
                if bgm_slot and bgm_slot.selected_asset_id:
                    asset = self._asset_from_slot(
                        bgm_slot,
                        role="audio",
                        source_relation="selected_bgm",
                    )
                    if asset is not None:
                        assets.append(asset)
        return _dedupe_assets(assets), warnings

    def _asset_from_relation(
        self,
        relation: WorkflowAssetRelationV2,
        *,
        role: str,
    ) -> tuple[V2ReferenceAsset | None, V2ReferenceWarning | None]:
        version_id = str(relation.metadata.get("version_id") or "")
        if not version_id:
            version_id = self._first_version_id(relation.source_asset_id) or ""
        if not version_id:
            return None, V2ReferenceWarning(
                code="reference_version_missing",
                asset_id=relation.source_asset_id,
                message="Reference asset version was not found.",
            )
        record = self._asset_store.load_asset_version(relation.source_asset_id, version_id)
        if record is None:
            return None, V2ReferenceWarning(
                code="reference_metadata_missing",
                asset_id=relation.source_asset_id,
                message="Reference asset metadata was not found.",
            )
        return _reference_asset(record, role=role, source_relation=relation.relation_type), None

    def _asset_from_slot(
        self,
        slot: WorkflowSlotV2,
        *,
        role: str,
        source_relation: str,
    ) -> V2ReferenceAsset | None:
        asset_id = slot.selected_asset_id or slot.current_working_asset_id
        version_id = slot.selected_version_id or slot.current_working_version_id
        if not version_id:
            version_id = self._first_version_id(asset_id)
        if not asset_id or not version_id:
            return None
        record = self._asset_store.load_asset_version(asset_id, version_id)
        if record is None:
            return None
        return _reference_asset(record, role=role, source_relation=source_relation)

    def _first_version_id(self, asset_id: str | None) -> str | None:
        if not asset_id:
            return None
        root = self._data_dir / "assets" / "metadata" / asset_id
        if not root.exists():
            return None
        first = next(iter(sorted(root.glob("*.json"))), None)
        return first.stem if first else None


def _reference_asset(
    record: WorkflowAssetVersionV2,
    *,
    role: str,
    source_relation: str,
) -> V2ReferenceAsset:
    semantic_type = _normalize_semantic_type(record.semantic_type or "", record.media_type)
    return V2ReferenceAsset(
        asset_id=record.asset_id,
        version_id=record.version_id,
        slot_id=record.slot_id,
        role=role,
        semantic_type=semantic_type,
        media_type=record.media_type,
        public_url=record.public_url or f"/media/{record.file_path}",
        local_path=record.file_path,
        display_name=_display_name(record, semantic_type),
        source_relation=source_relation,
        metadata=_light_metadata(record.metadata),
    )


def _provider_assets(
    slot: WorkflowSlotV2,
    assets: list[V2ReferenceAsset],
) -> tuple[list[V2ReferenceAsset], list[V2ReferenceWarning]]:
    supported_media = _provider_supported_reference_media(slot)
    provider_assets: list[V2ReferenceAsset] = []
    warnings: list[V2ReferenceWarning] = []
    for asset in assets:
        if asset.media_type not in supported_media:
            warnings.append(
                V2ReferenceWarning(
                    code="provider_reference_degraded",
                    asset_id=asset.asset_id,
                    message=(
                        "Provider does not support this reference media type; "
                        "asset will be used only as text context."
                    ),
                )
            )
            continue
        provider_assets.append(asset)
    return _dedupe_assets(provider_assets), warnings


def _provider_supported_reference_media(slot: WorkflowSlotV2) -> set[str]:
    if slot.slot_type == "final_video":
        return {"video", "audio"}
    if slot.media_type == "audio":
        return {"audio"}
    if slot.media_type == "video":
        return {"image", "video"}
    if slot.media_type == "image":
        return {"image"}
    return set()


def _llm_asset(asset: V2ReferenceAsset) -> V2ReferenceAsset:
    return asset.model_copy(
        update={"local_path": None, "metadata": _light_metadata(asset.metadata)}
    )


def _text_context(
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
) -> V2ReferenceBundleTextContext:
    user_summary = item.shot_summary_prompt if item.item_type == "shot" else item.item_prompt
    if not user_summary:
        user_summary = slot.slot_prompt
    provider_prompt = slot.slot_prompt or item.item_prompt or item.shot_summary_prompt
    if slot.slot_type == "final_video":
        provider_prompt = None
    return V2ReferenceBundleTextContext(
        user_summary_prompt=user_summary,
        summary_prompt_source=item.prompt_source
        if item.prompt_source in {"user", "system", "agent", "provider"}
        else "system",
        system_context=(
            "Use selected product, character, and scene references when available. "
            f"Workflow aspect ratio is {workflow.aspect_ratio}."
        ),
        provider_prompt=provider_prompt,
        negative_prompt=slot.negative_prompt,
    )


def _role_from_relation(relation: WorkflowAssetRelationV2) -> str:
    role = relation.metadata.get("reference_role") or relation.metadata.get("reference_kind")
    if isinstance(role, str) and role:
        return role
    return "style"


def _role_for_slot(slot: WorkflowSlotV2) -> str:
    if slot.node_id == "product-generation":
        return "product"
    if slot.node_id == "scene-generation":
        return "scene"
    if slot.node_id == "bgm":
        return "audio"
    if slot.slot_type.startswith("shot_"):
        return "composition"
    return "identity"


def _shot_reference_slots(workflow: WorkflowV2, item: WorkflowItemV2) -> list[WorkflowSlotV2]:
    slots: list[WorkflowSlotV2] = []
    for item_id in item.reference_item_ids:
        source_item = _find_item_any_node(workflow, item_id)
        if source_item is None:
            continue
        slot_type = _main_slot_type_for_item(source_item)
        if slot_type is None:
            continue
        slot = _slot_by_type(source_item, slot_type)
        if slot is not None and slot.selected_asset_id:
            slots.append(slot)
    return slots


def _find_item_any_node(workflow: WorkflowV2, item_id: str) -> WorkflowItemV2 | None:
    for node in workflow.nodes:
        for item in node.items:
            if item.lifecycle_state == "active" and item.item_id == item_id:
                return item
    return None


def _main_slot_type_for_item(item: WorkflowItemV2) -> str | None:
    if item.item_type == "product":
        return "product_main_image"
    if item.item_type == "character":
        return "character_main_image"
    if item.item_type == "scene":
        return "scene_main_image"
    return None


def _soft_dependency_warnings(workflow: WorkflowV2) -> list[V2ReferenceWarning]:
    warnings: list[V2ReferenceWarning] = []
    for slot in _workflow_slots(workflow):
        if slot.slot_type not in {
            "product_multi_view_grid",
            "character_three_view",
            "scene_multi_view_grid",
            "bgm_audio",
        }:
            continue
        if slot.status != "failed":
            continue
        error = slot.metadata.get("error")
        error_code = slot.metadata.get("generation_error_code")
        if not error_code and isinstance(error, dict):
            error_code = error.get("code")
        warnings.append(
            V2ReferenceWarning(
                code="soft_dependency_failed",
                asset_id=slot.slot_id,
                message=(
                    f"Soft dependency {slot.slot_type} is unavailable"
                    + (f": {error_code}" if error_code else ".")
                ),
            )
        )
    return warnings


def _dedupe_assets(assets: list[V2ReferenceAsset]) -> list[V2ReferenceAsset]:
    deduped: dict[tuple[str, str, str | None, str], V2ReferenceAsset] = {}
    for asset in assets:
        key = (asset.asset_id, asset.version_id, asset.slot_id, asset.role)
        deduped.setdefault(key, asset)
    return list(deduped.values())


def _light_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    heavy_keys = {
        "raw_response",
        "source_asset",
        "base64",
        "bytes",
        "exif",
        "canonical_provider_payload",
        "provider_payload",
        "provider_payload_snapshot",
        "provider_asset",
        "prompt_snapshot",
        "prompt_audit",
        "prompt_lineage",
        "prompt_registry_ref",
        "prompt_isolation_audit",
        "provider_prompt_contract",
        "reference_audit",
        "reference_delivery_audit",
        "quality_gate_result",
        "quality_gate_warnings",
        "generation_integrity",
        "integrity_audit",
        "agent_route",
        "latest_reference_audit",
        "latest_reference_delivery_audit",
        "provider_input_audit",
        "quality_flags",
    }
    return {key: value for key, value in metadata.items() if key not in heavy_keys}


def _find_slot(workflow: WorkflowV2, slot_id: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in _workflow_slots(workflow) if slot.slot_id == slot_id), None)


def _find_item(workflow: WorkflowV2, node_id: str, item_id: str) -> WorkflowItemV2 | None:
    node = next((node for node in workflow.nodes if node.node_id == node_id), None)
    if node is None:
        return None
    return next((item for item in node.items if item.item_id == item_id), None)


def _slot_by_type(item: WorkflowItemV2, slot_type: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in item.slots if slot.slot_type == slot_type), None)


def _workflow_slots(workflow: WorkflowV2) -> list[WorkflowSlotV2]:
    return [slot for node in workflow.nodes for item in node.items for slot in item.slots]


def _storyboard_items(workflow: WorkflowV2) -> list[WorkflowItemV2]:
    storyboard = next((node for node in workflow.nodes if node.node_id == "storyboard"), None)
    if storyboard is None:
        return []
    return sorted(storyboard.items, key=lambda item: item.shot_index or 0)
