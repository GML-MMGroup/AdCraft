import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import Settings, get_settings
from app.schemas.asset_library import LibraryAsset, LibraryEntity
from app.schemas.workflow_v2 import (
    AbsorbAssetRequestV2,
    AbsorbAssetResponseV2,
    AddSlotReferenceRequestV2,
    AddSlotReferenceResponseV2,
    SelectSlotVersionRequestV2,
    SelectSlotVersionResponseV2,
    V2ReferenceAssetMutationResponse,
    V2RegisterLibraryReferenceRequest,
    V2RegisterReferenceRequest,
    WorkflowAssetListResponseV2,
    WorkflowAssetRelationV2,
    WorkflowAssetSemanticTypeV2,
    WorkflowAssetStateV2,
    WorkflowAssetVersionV2,
    WorkflowAssetVersionsResponseV2,
    WorkflowAssetVersionViewV2,
    WorkflowAssetViewV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_authoring import WorkflowRevisionChangeSource
from app.services.agent_trace import utc_now
from app.services.asset_library import AssetLibraryError, AssetLibraryService
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_input_assets import (
    V2InputAssetError,
    V2InputAssetService,
    asset_locator,
    validate_assets_relative_file,
)
from app.services.v2_runtime_events import V2RuntimeEventService
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime


class V2WorkflowAssetError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2WorkflowAssetService:
    def __init__(self, data_dir: Path, settings: Settings | None = None) -> None:
        self._data_dir = data_dir
        self._settings = settings or get_settings()
        self._asset_store = V2AssetStoreService(data_dir)
        self._authoring_runtime = create_workflow_authoring_runtime(data_dir)
        self._events = V2RuntimeEventService(data_dir)
        self._input_assets = V2InputAssetService(settings=self._settings, data_dir=data_dir)
        self._asset_library = AssetLibraryService(self._settings)

    def list_workflow_assets(
        self,
        workflow_id: str,
        *,
        media_type: str | None = None,
        semantic_type: str | None = None,
        node_id: str | None = None,
        item_id: str | None = None,
        slot_id: str | None = None,
        state: str | None = None,
        owner_type: str | None = None,
    ) -> WorkflowAssetListResponseV2:
        workflow = self._load_workflow(workflow_id)
        relations = self._asset_store.list_relations(target_workflow_id=workflow_id)
        rows = self._rows_from_relations(workflow, relations)
        rows.extend(self._rows_from_slot_pointers(workflow, relations))
        rows = _dedupe_rows(rows)
        rows = [
            row
            for row in rows
            if (media_type is None or row.media_type == media_type)
            and (semantic_type is None or row.semantic_type == semantic_type)
            and (node_id is None or row.node_id == node_id)
            and (item_id is None or row.item_id == item_id)
            and (slot_id is None or row.slot_id == slot_id)
            and (state is None or row.state == state)
            and (owner_type is None or row.owner_type == owner_type)
        ]
        return WorkflowAssetListResponseV2(workflow_id=workflow_id, assets=rows)

    def list_asset_versions(
        self,
        workflow_id: str,
        asset_id: str,
    ) -> WorkflowAssetVersionsResponseV2:
        workflow = self._load_workflow(workflow_id)
        relations = self._asset_store.list_relations(
            target_workflow_id=workflow_id,
            source_asset_id=asset_id,
        )
        if not relations:
            raise V2WorkflowAssetError("asset_not_in_workflow")
        versions: list[WorkflowAssetVersionViewV2] = []
        seen: set[tuple[str, str]] = set()
        selected_version_id: str | None = None
        working_version_id: str | None = None
        for relation in relations:
            state = _state_from_relation(relation)
            if state is None:
                continue
            version_id = str(relation.metadata.get("version_id") or "")
            if not version_id:
                version_id = self._first_version_id(asset_id) or ""
            if not version_id:
                continue
            record = self._asset_store.load_asset_version(asset_id, version_id)
            if record is None or record.workflow_id not in {workflow_id, None}:
                continue
            key = (version_id, state)
            if key in seen:
                continue
            seen.add(key)
            if state == "selected":
                selected_version_id = version_id
            if state == "working":
                working_version_id = version_id
            versions.append(_version_view(workflow, record, state, relation))

        for slot in _workflow_slots(workflow):
            if slot.selected_asset_id == asset_id:
                selected_version_id = (
                    selected_version_id
                    or slot.selected_version_id
                    or self._first_version_id(asset_id)
                )
            if slot.current_working_asset_id == asset_id:
                working_version_id = working_version_id or slot.current_working_version_id

        if not versions:
            raise V2WorkflowAssetError("asset_version_not_found")
        return WorkflowAssetVersionsResponseV2(
            workflow_id=workflow_id,
            asset_id=asset_id,
            selected_version_id=selected_version_id,
            working_version_id=working_version_id,
            versions=versions,
        )

    def select_slot_version(
        self,
        workflow_id: str,
        slot_id: str,
        request: SelectSlotVersionRequestV2,
    ) -> SelectSlotVersionResponseV2:
        workflow = self._load_workflow(workflow_id)
        slot = _find_slot(workflow, slot_id)
        if slot is None:
            raise V2WorkflowAssetError("slot_not_found")
        record = self._asset_store.load_asset_version(request.asset_id, request.version_id)
        if record is None:
            raise V2WorkflowAssetError("asset_version_not_found")
        self._validate_record_in_workflow(record, workflow_id)
        self._validate_slot_record_compatible(slot, record)
        old_selected_asset_id = slot.selected_asset_id
        old_selected_version_id = slot.selected_version_id or self._first_version_id(
            old_selected_asset_id
        )
        if old_selected_asset_id and old_selected_version_id:
            slot.history_version_ids = list(
                dict.fromkeys([*slot.history_version_ids, old_selected_version_id])
            )
            self._create_slot_relation(
                "history_version_for_slot",
                workflow,
                slot,
                old_selected_asset_id,
                old_selected_version_id,
                source_action="select_version",
            )
        self._asset_store.delete_slot_relations(
            target_workflow_id=workflow_id,
            target_slot_id=slot_id,
            relation_type="selected_for_slot",
        )
        selected = self._create_slot_relation(
            "selected_for_slot",
            workflow,
            slot,
            request.asset_id,
            request.version_id,
            source_action="select_version",
        )
        slot.selected_asset_id = request.asset_id
        slot.selected_version_id = request.version_id
        slot.status = "completed"
        if (
            slot.current_working_asset_id == request.asset_id
            and slot.current_working_version_id == request.version_id
        ):
            self._asset_store.delete_slot_relations(
                target_workflow_id=workflow_id,
                target_slot_id=slot_id,
                relation_type="working_version_for_slot",
            )
            slot.current_working_asset_id = None
            slot.current_working_version_id = None
        self._commit_semantic_then_operational(
            workflow,
            source="selected_version_change",
        )
        self._events.append_event(
            workflow_id,
            "slot_selected_version_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=request.asset_id,
            version_id=request.version_id,
            payload={"relation_id": selected.relation_id},
        )
        self._events.append_event(
            workflow_id,
            "runtime_snapshot_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=request.asset_id,
            version_id=request.version_id,
            payload={"status": slot.status},
        )
        return SelectSlotVersionResponseV2(
            workflow_id=workflow_id,
            slot_id=slot_id,
            selected_asset_id=request.asset_id,
            selected_version_id=request.version_id,
            events=["slot_selected_version_updated", "runtime_snapshot_updated"],
        )

    def select_slot_version_by_version_id(
        self,
        workflow_id: str,
        slot_id: str,
        version_id: str,
    ) -> SelectSlotVersionResponseV2:
        workflow = self._load_workflow(workflow_id)
        slot = _find_slot(workflow, slot_id)
        if slot is None:
            raise V2WorkflowAssetError("slot_not_found")
        record = self._asset_store.find_asset_version(slot_id=slot_id, version_id=version_id)
        if record is None:
            record = _record_from_slot_relations(
                self._asset_store,
                workflow_id=workflow_id,
                slot_id=slot_id,
                version_id=version_id,
            )
        if record is None:
            raise V2WorkflowAssetError("asset_version_not_found")
        return self.select_slot_version(
            workflow_id,
            slot_id,
            SelectSlotVersionRequestV2(asset_id=record.asset_id, version_id=record.version_id),
        )

    def add_slot_reference(
        self,
        workflow_id: str,
        slot_id: str,
        request: AddSlotReferenceRequestV2,
    ) -> AddSlotReferenceResponseV2:
        workflow = self._load_workflow(workflow_id)
        slot = _find_slot(workflow, slot_id)
        if slot is None:
            raise V2WorkflowAssetError("slot_not_found")
        record = self._asset_store.load_asset_version(request.asset_id, request.version_id)
        if record is None:
            raise V2WorkflowAssetError("asset_version_not_found")
        self._validate_record_referenceable(record, workflow_id)
        if not _reference_role_compatible(request.reference_role, record.media_type):
            raise V2WorkflowAssetError("reference_role_incompatible")
        relation = self._attach_record_to_slot(
            workflow,
            slot,
            record,
            reference_role=request.reference_role,
            source_action="add_slot_reference",
        )
        self._commit_semantic(workflow, source="reference_change")
        self._emit_reference_attached(workflow, slot, relation, request.reference_role)
        return AddSlotReferenceResponseV2(
            workflow_id=workflow_id,
            slot_id=slot_id,
            reference_asset_id=request.asset_id,
            reference_version_id=request.version_id,
            reference_role=request.reference_role,
            relation_id=relation.relation_id,
            events=["reference_attached", "runtime_snapshot_updated"],
        )

    def upload_slot_reference_assets(
        self,
        workflow_id: str,
        slot_id: str,
        *,
        files: list[UploadFile],
        reference_role: str | None = None,
        display_name: str | None = None,
        tags: list[str] | None = None,
    ) -> V2ReferenceAssetMutationResponse:
        workflow = self._load_workflow(workflow_id)
        slot = _find_slot(workflow, slot_id)
        if slot is None:
            raise V2WorkflowAssetError("slot_not_found")
        role = reference_role or _default_reference_role_for_slot(slot)
        if not files:
            raise V2WorkflowAssetError("upload_file_required")
        records: list[WorkflowAssetVersionV2] = []
        relations: list[WorkflowAssetRelationV2] = []
        try:
            for file in files:
                media_type = _media_type_hint(file)
                if not _slot_reference_media_compatible(slot, media_type):
                    raise V2WorkflowAssetError("asset_slot_incompatible")
                if not _reference_role_compatible(role, media_type):
                    raise V2WorkflowAssetError("reference_role_incompatible")
                record = self._input_assets.save_uploaded_asset(
                    file=file,
                    semantic_type=_semantic_type_for_reference(role, slot),
                    display_name=display_name,
                    tags=tags,
                    workflow_id=workflow_id,
                    node_id=slot.node_id,
                    item_id=slot.item_id,
                    slot_id=slot.slot_id,
                )
                records.append(record)
                relations.append(
                    self._attach_record_to_slot(
                        workflow,
                        slot,
                        record,
                        reference_role=role,
                        source_action="slot_reference_upload",
                    )
                )
        except V2InputAssetError as exc:
            raise V2WorkflowAssetError(exc.code, str(exc)) from exc
        self._commit_semantic(workflow, source="reference_change")
        events: list[str] = []
        for record in records:
            self._events.append_event(
                workflow_id,
                "asset_version_created",
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                asset_id=record.asset_id,
                version_id=record.version_id,
                payload={
                    "source_type": record.source_type,
                    "semantic_type": record.semantic_type,
                },
            )
            events.append("asset_version_created")
        for relation in relations:
            self._emit_reference_attached(workflow, slot, relation, role)
            events.extend(["reference_attached", "runtime_snapshot_updated"])
        return V2ReferenceAssetMutationResponse(
            workflow=workflow,
            assets=[
                _asset_view(workflow, record, "reference", [relation.relation_id], relation)
                for record, relation in zip(records, relations, strict=True)
            ],
            relations=relations,
            runtime=self._events.runtime_snapshot(workflow),
            events=list(dict.fromkeys(events)),
        )

    def register_reference(
        self,
        workflow_id: str,
        request: V2RegisterReferenceRequest,
    ) -> V2ReferenceAssetMutationResponse:
        workflow = self._load_workflow(workflow_id)
        record, created = self._record_from_register_source(workflow, request)
        relations: list[WorkflowAssetRelationV2] = []
        events: list[str] = []
        if created:
            self._events.append_event(
                workflow_id,
                "asset_version_created",
                node_id=record.node_id,
                item_id=record.item_id,
                slot_id=record.slot_id,
                asset_id=record.asset_id,
                version_id=record.version_id,
                payload={
                    "source_type": record.source_type,
                    "semantic_type": record.semantic_type,
                },
            )
            events.append("asset_version_created")
        if request.target is not None:
            slot = _find_slot(workflow, request.target.slot_id)
            if slot is None:
                raise V2WorkflowAssetError("slot_not_found")
            role = request.reference_role or _default_reference_role_for_slot(slot)
            if not _slot_reference_media_compatible(slot, record.media_type):
                raise V2WorkflowAssetError("asset_slot_incompatible")
            if not _reference_role_compatible(role, record.media_type):
                raise V2WorkflowAssetError("reference_role_incompatible")
            relation = self._attach_record_to_slot(
                workflow,
                slot,
                record,
                reference_role=role,
                source_action="register_reference",
            )
            relations.append(relation)
            self._commit_semantic(workflow, source="reference_change")
            self._emit_reference_attached(workflow, slot, relation, role)
            events.extend(["reference_attached", "runtime_snapshot_updated"])
        return V2ReferenceAssetMutationResponse(
            workflow=workflow,
            assets=[
                _asset_view(workflow, record, "reference", [relation.relation_id], relation)
                if relation
                else _ownerless_asset_view(workflow, record, "reference")
                for relation in (relations or [None])
            ],
            relations=relations,
            runtime=self._events.runtime_snapshot(workflow),
            events=list(dict.fromkeys(events)),
        )

    def register_library_reference(
        self,
        workflow_id: str,
        request: V2RegisterLibraryReferenceRequest,
    ) -> V2ReferenceAssetMutationResponse:
        workflow = self._load_workflow(workflow_id)
        entity, library_asset, media_type = self.resolve_library_reference(request)
        slot = _find_slot(workflow, request.target.slot_id) if request.target else None
        if request.target is not None and slot is None:
            raise V2WorkflowAssetError("slot_not_found")
        role = request.reference_role or (
            _default_reference_role_for_slot(slot) if slot else _default_reference_role(media_type)
        )
        if slot is not None and not _slot_reference_media_compatible(slot, media_type):
            raise V2WorkflowAssetError("asset_slot_incompatible")
        if not _reference_role_compatible(role, media_type):
            raise V2WorkflowAssetError("reference_role_incompatible")
        semantic_type = request.semantic_type or (
            _semantic_type_for_reference(role, slot) if slot else library_asset.semantic_type
        )
        record = self._import_library_asset_record(
            workflow,
            entity,
            library_asset,
            slot=slot,
            media_type=media_type,
            semantic_type=semantic_type,
        )
        self._events.append_event(
            workflow_id,
            "asset_version_created",
            node_id=record.node_id,
            item_id=record.item_id,
            slot_id=record.slot_id,
            asset_id=record.asset_id,
            version_id=record.version_id,
            payload={
                "source_type": record.source_type,
                "semantic_type": record.semantic_type,
                "library_entity_id": entity.entity_id,
                "library_asset_id": library_asset.asset_id,
            },
        )
        events = ["asset_version_created"]
        relations: list[WorkflowAssetRelationV2] = []
        if slot is not None:
            relation = self._attach_record_to_slot(
                workflow,
                slot,
                record,
                reference_role=role,
                source_action="register_library_reference",
            )
            relation = relation.model_copy(
                update={
                    "metadata": {
                        **relation.metadata,
                        "library_entity_id": entity.entity_id,
                        "library_asset_id": library_asset.asset_id,
                    }
                }
            )
            self._asset_store.save_relation(relation)
            self._commit_semantic(workflow, source="reference_change")
            self._emit_reference_attached(workflow, slot, relation, role)
            relations.append(relation)
            events.extend(["reference_attached", "runtime_snapshot_updated"])
        return V2ReferenceAssetMutationResponse(
            workflow=workflow,
            assets=[
                _asset_view(workflow, record, "reference", [relation.relation_id], relation)
                if relation
                else _ownerless_asset_view(workflow, record, "reference")
                for relation in (relations or [None])
            ],
            relations=relations,
            runtime=self._events.runtime_snapshot(workflow),
            events=list(dict.fromkeys(events)),
        )

    def resolve_library_reference(
        self,
        request: V2RegisterLibraryReferenceRequest,
    ) -> tuple[LibraryEntity, LibraryAsset, str]:
        """Resolve a library reference before an import writes a V2 asset record."""

        entity, library_asset = self._library_asset_for_request(request)
        return entity, library_asset, _library_asset_media_type(library_asset)

    def _add_downstream_outdated_hint_from_slot(
        self,
        workflow: WorkflowV2,
        *,
        source_slot: WorkflowSlotV2,
        old_asset_id: str | None,
        new_asset_id: str,
    ) -> list[WorkflowSlotV2]:
        if not old_asset_id or old_asset_id == new_asset_id:
            return []
        hint = {
            "source_slot_id": source_slot.slot_id,
            "old_asset_id": old_asset_id,
            "new_asset_id": new_asset_id,
            "reason": "upstream_selected_version_changed",
            "created_at": utc_now().isoformat(),
        }
        affected_slots: list[WorkflowSlotV2] = []
        for slot in _downstream_outdated_slots(workflow, source_slot):
            if self._add_outdated_hint_to_slot(workflow, slot, hint):
                affected_slots.append(slot)
        self._emit_outdated_hint_scope_events(workflow, affected_slots, hint)
        return affected_slots

    def _add_outdated_hint_to_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        hint: dict[str, Any],
    ) -> bool:
        sources = [
            dict(source)
            for source in slot.metadata.get("outdated_sources", [])
            if isinstance(source, dict)
        ]
        duplicate = any(
            source.get("source_slot_id") == hint.get("source_slot_id")
            and source.get("old_asset_id") == hint.get("old_asset_id")
            and source.get("new_asset_id") == hint.get("new_asset_id")
            and source.get("reason") == hint.get("reason")
            for source in sources
        )
        if duplicate:
            return False
        sources.append(dict(hint))
        slot.metadata["outdated_hint"] = True
        slot.metadata["outdated_sources"] = sources
        slot.metadata["reference_outdated"] = True
        slot.metadata["linked_source_has_new_version"] = True
        slot.metadata["outdated_source_asset_id"] = hint.get("old_asset_id")
        slot.metadata["latest_source_asset_id"] = hint.get("new_asset_id")
        slot.metadata["outdated_at"] = hint.get("created_at")
        self._events.append_event(
            workflow.workflow_id,
            "slot_outdated_hint_added",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload=dict(hint),
        )
        self._events.append_event(
            workflow.workflow_id,
            "weak_link_hint_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={
                "outdated_source_asset_id": hint.get("old_asset_id"),
                "latest_source_asset_id": hint.get("new_asset_id"),
            },
        )
        return True

    def _emit_outdated_hint_scope_events(
        self,
        workflow: WorkflowV2,
        slots: list[WorkflowSlotV2],
        hint: dict[str, Any],
    ) -> None:
        seen_items: set[tuple[str, str]] = set()
        seen_nodes: set[str] = set()
        for slot in slots:
            item_key = (slot.node_id, slot.item_id)
            if item_key not in seen_items:
                seen_items.add(item_key)
                self._events.append_event(
                    workflow.workflow_id,
                    "item_outdated_hint_added",
                    node_id=slot.node_id,
                    item_id=slot.item_id,
                    payload=dict(hint),
                )
            if slot.node_id not in seen_nodes:
                seen_nodes.add(slot.node_id)
                self._events.append_event(
                    workflow.workflow_id,
                    "node_outdated_hint_added",
                    node_id=slot.node_id,
                    payload=dict(hint),
                )

    def absorb_asset(
        self,
        workflow_id: str,
        asset_id: str,
        request: AbsorbAssetRequestV2,
    ) -> AbsorbAssetResponseV2:
        workflow = self._load_workflow(workflow_id)
        record = self._asset_store.load_asset_version(asset_id, request.version_id)
        if record is None:
            raise V2WorkflowAssetError("asset_version_not_found")
        self._validate_record_in_workflow(record, workflow_id)
        target_slot = _resolve_target_slot(
            workflow, request.target_node_id, request.target_item_id, request.target_slot_id
        )
        if target_slot is None:
            raise V2WorkflowAssetError("slot_not_found")
        if not _absorb_compatible(record, target_slot):
            raise V2WorkflowAssetError("absorb_target_incompatible")
        relations: list[WorkflowAssetRelationV2] = [
            self._asset_store.create_relation(
                relation_type="absorbed_into",
                source_asset_id=asset_id,
                target_workflow_id=workflow_id,
                target_node_id=target_slot.node_id,
                target_item_id=target_slot.item_id,
                target_slot_id=target_slot.slot_id,
                metadata={"version_id": request.version_id, "mode": request.mode},
            )
        ]
        if request.mode == "selected":
            self.select_slot_version(
                workflow_id,
                target_slot.slot_id,
                SelectSlotVersionRequestV2(asset_id=asset_id, version_id=request.version_id),
            )
        else:
            relations.append(
                self._asset_store.create_relation(
                    relation_type="reference_for_slot",
                    source_asset_id=asset_id,
                    target_workflow_id=workflow_id,
                    target_node_id=target_slot.node_id,
                    target_item_id=target_slot.item_id,
                    target_slot_id=target_slot.slot_id,
                    metadata={
                        "version_id": request.version_id,
                        "reference_role": _default_reference_role(record.media_type),
                        "reference_kind": "absorbed",
                    },
                )
            )
            _append_unique(target_slot.explicit_reference_ids, asset_id)
            for relation in relations:
                _append_unique_metadata(
                    target_slot.metadata,
                    "reference_relation_ids",
                    relation.relation_id,
                )
            self._commit_semantic(workflow, source="reference_change")
        self._events.append_event(
            workflow_id,
            "asset_absorbed_into_slot",
            node_id=target_slot.node_id,
            item_id=target_slot.item_id,
            slot_id=target_slot.slot_id,
            asset_id=asset_id,
            version_id=request.version_id,
            payload={"relation_ids": [relation.relation_id for relation in relations]},
        )
        return AbsorbAssetResponseV2(
            workflow_id=workflow_id,
            asset_id=asset_id,
            version_id=request.version_id,
            target_slot_id=target_slot.slot_id,
            mode=request.mode,
            relation_ids=[relation.relation_id for relation in relations],
            events=["asset_absorbed_into_slot"],
        )

    def _load_workflow(self, workflow_id: str) -> WorkflowV2:
        try:
            return self._authoring_runtime.read_model.assemble(workflow_id)
        except Exception as exc:
            code = getattr(exc, "code", "workflow_not_found")
            raise V2WorkflowAssetError(str(code), str(exc)) from exc

    def _commit_semantic(
        self,
        workflow: WorkflowV2,
        *,
        source: WorkflowRevisionChangeSource,
    ) -> WorkflowV2:
        if workflow.state_version is None:
            raise V2WorkflowAssetError("workflow_authoring_version_missing")
        return self._authoring_runtime.service.commit_semantic_workflow(
            workflow,
            expected_version=workflow.state_version,
            source=source,
        )

    def _persist_operational(self, workflow: WorkflowV2) -> WorkflowV2:
        if workflow.semantic_revision_no is None:
            raise V2WorkflowAssetError("workflow_authoring_version_missing")
        self._authoring_runtime.projection.save_operational_overlay(
            workflow,
            expected_revision_no=workflow.semantic_revision_no,
        )
        return self._authoring_runtime.read_model.assemble(workflow.workflow_id)

    def _commit_semantic_then_operational(
        self,
        workflow: WorkflowV2,
        *,
        source: WorkflowRevisionChangeSource,
    ) -> WorkflowV2:
        self._commit_semantic(workflow, source=source)
        return self._persist_operational(workflow)

    def _library_asset_for_request(
        self,
        request: V2RegisterLibraryReferenceRequest,
    ) -> tuple[LibraryEntity, LibraryAsset]:
        try:
            detail = self._asset_library.get_entity(
                request.library_entity_id, include_archived=False
            )
        except AssetLibraryError as exc:
            raise V2WorkflowAssetError(exc.code, str(exc)) from exc
        assets = [asset for asset in detail.assets if not asset.is_archived]
        if request.library_asset_id:
            assets = [asset for asset in assets if asset.asset_id == request.library_asset_id]
        if not assets:
            raise V2WorkflowAssetError("asset_library_asset_not_found")
        return detail.entity, assets[0]

    def _import_library_asset_record(
        self,
        workflow: WorkflowV2,
        entity: LibraryEntity,
        library_asset: LibraryAsset,
        *,
        slot: WorkflowSlotV2 | None,
        media_type: str,
        semantic_type: str,
    ) -> WorkflowAssetVersionV2:
        source_path = _library_asset_source_path(self._data_dir, library_asset)
        asset_id = f"asset_{uuid4_hex()}"
        version_id = f"ver_{uuid4_hex()}"
        suffix = _library_asset_suffix(source_path, media_type)
        relative_path = Path("assets") / "originals" / asset_id / f"{version_id}{suffix}"
        output_path = validate_v2_data_path(
            self._data_dir,
            self._data_dir / relative_path,
            operation="v2-register-library-reference-import",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, output_path)
        record = WorkflowAssetVersionV2(
            asset_id=asset_id,
            version_id=version_id,
            media_type=media_type,  # type: ignore[arg-type]
            source_type="imported",
            file_path=relative_path.as_posix(),
            public_url=f"/media/{relative_path.as_posix()}",
            workflow_id=workflow.workflow_id if slot else None,
            node_id=slot.node_id if slot else None,
            item_id=slot.item_id if slot else None,
            slot_id=slot.slot_id if slot else None,
            semantic_type=semantic_type,
            library_entity_id=entity.entity_id,
            created_by="v2-library-reference",
            created_at=utc_now().isoformat(),
            metadata={
                "display_name": entity.display_name,
                "library_entity_id": entity.entity_id,
                "library_asset_id": library_asset.asset_id,
                "source_uri": library_asset.uri,
                "source_semantic_type": library_asset.semantic_type,
                "mime_type": library_asset.mime_type,
                "tags": list(entity.tags),
                "registered_source": "asset_library",
            },
        )
        return self._asset_store.save_asset_version(record)

    def _rows_from_relations(
        self,
        workflow: WorkflowV2,
        relations: list[WorkflowAssetRelationV2],
    ) -> list[WorkflowAssetViewV2]:
        rows: list[WorkflowAssetViewV2] = []
        for relation in relations:
            state = _state_from_relation(relation)
            if state is None:
                continue
            version_id = str(relation.metadata.get("version_id") or "")
            if not version_id:
                version_id = self._first_version_id(relation.source_asset_id) or ""
            if not version_id:
                continue
            record = self._asset_store.load_asset_version(relation.source_asset_id, version_id)
            if record is None or record.workflow_id not in {workflow.workflow_id, None}:
                continue
            rows.append(_asset_view(workflow, record, state, [relation.relation_id], relation))
        return rows

    def _rows_from_slot_pointers(
        self,
        workflow: WorkflowV2,
        relations: list[WorkflowAssetRelationV2],
    ) -> list[WorkflowAssetViewV2]:
        existing = {
            (relation.source_asset_id, relation.target_slot_id, relation.relation_type)
            for relation in relations
        }
        rows: list[WorkflowAssetViewV2] = []
        for slot in _workflow_slots(workflow):
            if (
                slot.selected_asset_id
                and (
                    slot.selected_asset_id,
                    slot.slot_id,
                    "selected_for_slot",
                )
                not in existing
            ):
                version_id = self._first_version_id(slot.selected_asset_id)
                if version_id:
                    record = self._asset_store.load_asset_version(
                        slot.selected_asset_id, version_id
                    )
                    if record and record.workflow_id == workflow.workflow_id:
                        rows.append(_asset_view(workflow, record, "selected", [], None))
            if (
                slot.current_working_asset_id
                and (
                    slot.current_working_asset_id,
                    slot.slot_id,
                    "working_version_for_slot",
                )
                not in existing
            ):
                version_id = slot.current_working_version_id
                if version_id:
                    record = self._asset_store.load_asset_version(
                        slot.current_working_asset_id,
                        version_id,
                    )
                    if record and record.workflow_id == workflow.workflow_id:
                        rows.append(_asset_view(workflow, record, "working", [], None))
        return rows

    def _first_version_id(self, asset_id: str | None) -> str | None:
        if not asset_id:
            return None
        root = self._data_dir / "assets" / "metadata" / asset_id
        validate_v2_data_path(self._data_dir, root, operation="v2-asset-version-list")
        if not root.exists():
            return None
        first = next(iter(sorted(root.glob("*.json"))), None)
        return first.stem if first else None

    def _validate_record_in_workflow(
        self, record: WorkflowAssetVersionV2, workflow_id: str
    ) -> None:
        if record.workflow_id != workflow_id:
            raise V2WorkflowAssetError("asset_not_in_workflow")

    def _validate_record_referenceable(
        self, record: WorkflowAssetVersionV2, workflow_id: str
    ) -> None:
        if record.workflow_id not in {workflow_id, None}:
            raise V2WorkflowAssetError("asset_not_in_workflow")

    def _validate_slot_record_compatible(
        self,
        slot: WorkflowSlotV2,
        record: WorkflowAssetVersionV2,
    ) -> None:
        if slot.media_type != record.media_type:
            raise V2WorkflowAssetError("asset_slot_incompatible")
        expected = _normalize_semantic_type(slot.slot_type, slot.media_type)
        actual = _normalize_semantic_type(record.semantic_type or "", record.media_type)
        if expected.startswith("free_"):
            return
        if actual.startswith("free_"):
            return
        if expected != actual:
            raise V2WorkflowAssetError("asset_slot_incompatible")

    def _create_slot_relation(
        self,
        relation_type: str,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        asset_id: str,
        version_id: str,
        *,
        source_action: str,
    ) -> WorkflowAssetRelationV2:
        return self._asset_store.create_relation(
            relation_type=relation_type,  # type: ignore[arg-type]
            source_asset_id=asset_id,
            target_workflow_id=workflow.workflow_id,
            target_node_id=slot.node_id,
            target_item_id=slot.item_id,
            target_slot_id=slot.slot_id,
            metadata={
                "version_id": version_id,
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
                "semantic_type": _normalize_semantic_type(slot.slot_type, slot.media_type),
                "source_action": source_action,
                "created_at": utc_now().isoformat(),
            },
        )

    def _attach_record_to_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        record: WorkflowAssetVersionV2,
        *,
        reference_role: str,
        source_action: str,
    ) -> WorkflowAssetRelationV2:
        relation = self._asset_store.create_relation(
            relation_type="reference_for_slot",
            source_asset_id=record.asset_id,
            target_workflow_id=workflow.workflow_id,
            target_node_id=slot.node_id,
            target_item_id=slot.item_id,
            target_slot_id=slot.slot_id,
            metadata={
                "version_id": record.version_id,
                "source_version_id": record.version_id,
                "reference_kind": "explicit",
                "reference_role": reference_role,
                "slot_type": slot.slot_type,
                "media_type": record.media_type,
                "semantic_type": record.semantic_type,
                "source_action": source_action,
                "created_at": utc_now().isoformat(),
            },
        )
        _append_unique(slot.explicit_reference_ids, record.asset_id)
        _append_unique_metadata(slot.metadata, "reference_relation_ids", relation.relation_id)
        return relation

    def _emit_reference_attached(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        relation: WorkflowAssetRelationV2,
        reference_role: str,
    ) -> None:
        version_id = str(relation.metadata.get("version_id") or "")
        payload = {
            "relation_id": relation.relation_id,
            "relation_type": relation.relation_type,
            "reference_role": reference_role,
        }
        self._events.append_event(
            workflow.workflow_id,
            "reference_attached",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=relation.source_asset_id,
            version_id=version_id,
            payload=payload,
        )
        self._events.append_event(
            workflow.workflow_id,
            "slot_reference_added",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=relation.source_asset_id,
            version_id=version_id,
            payload=payload,
        )
        self._events.append_event(
            workflow.workflow_id,
            "runtime_snapshot_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=relation.source_asset_id,
            version_id=version_id,
            payload={"status": slot.status},
        )

    def _record_from_register_source(
        self,
        workflow: WorkflowV2,
        request: V2RegisterReferenceRequest,
    ) -> tuple[WorkflowAssetVersionV2, bool]:
        source = request.source
        if source.kind == "existing_v2_asset_version":
            if not source.asset_id or not source.version_id:
                raise V2WorkflowAssetError("asset_version_not_found")
            record = self._asset_store.load_asset_version(source.asset_id, source.version_id)
            if record is None:
                raise V2WorkflowAssetError("asset_version_not_found")
            self._validate_record_referenceable(record, workflow.workflow_id)
            return record, False
        if not source.file_path:
            raise V2WorkflowAssetError("asset_not_found")
        try:
            relative_path = validate_assets_relative_file(self._data_dir, source.file_path)
        except V2InputAssetError as exc:
            raise V2WorkflowAssetError(exc.code, str(exc)) from exc
        if not source.media_type or not source.semantic_type or not source.display_name:
            raise V2WorkflowAssetError("asset_version_not_found")
        slot = _find_slot(workflow, request.target.slot_id) if request.target else None
        record = WorkflowAssetVersionV2(
            asset_id=f"asset_{uuid4_hex()}",
            version_id=f"ver_{uuid4_hex()}",
            media_type=source.media_type,
            source_type="imported",
            file_path=relative_path.as_posix(),
            public_url=f"/media/{relative_path.as_posix()}",
            workflow_id=workflow.workflow_id if slot else None,
            node_id=slot.node_id if slot else None,
            item_id=slot.item_id if slot else None,
            slot_id=slot.slot_id if slot else None,
            semantic_type=source.semantic_type,
            created_by="v2-register-reference",
            metadata={
                "display_name": source.display_name,
                "tags": list(source.tags),
                "registered_source": "data_assets_file",
            },
        )
        return self._asset_store.save_asset_version(record), True


def _asset_view(
    workflow: WorkflowV2,
    record: WorkflowAssetVersionV2,
    state: WorkflowAssetStateV2,
    relation_ids: list[str],
    relation: WorkflowAssetRelationV2 | None,
) -> WorkflowAssetViewV2:
    slot = (
        _find_slot(workflow, relation.target_slot_id)
        if relation and relation.target_slot_id
        else None
    )
    node_id = relation.target_node_id if relation and relation.target_node_id else record.node_id
    item_id = relation.target_item_id if relation and relation.target_item_id else record.item_id
    slot_id = relation.target_slot_id if relation and relation.target_slot_id else record.slot_id
    slot_type = slot.slot_type if slot else (record.semantic_type or "")
    semantic_type = _normalize_semantic_type(record.semantic_type or slot_type, record.media_type)
    prompt = _prompt_fields(record)
    owner = _owner_fields(workflow, node_id, item_id, slot_id, slot_type, semantic_type)
    return WorkflowAssetViewV2(
        asset_id=record.asset_id,
        version_id=record.version_id,
        workflow_id=workflow.workflow_id,
        node_id=node_id,
        item_id=item_id,
        slot_id=slot_id,
        media_type=record.media_type,
        semantic_type=semantic_type,
        source_type=record.source_type,
        state=state,
        locator=asset_locator(record.asset_id, record.version_id),
        owner_type=owner["owner_type"],
        owner_node_id=owner["owner_node_id"],
        owner_item_id=owner["owner_item_id"],
        owner_slot_id=owner["owner_slot_id"],
        owner_display_name=owner["owner_display_name"],
        display_name=_display_name(record, semantic_type),
        public_url=record.public_url or f"/media/{record.file_path}",
        thumbnail_url=f"/media/{record.thumbnail_path}" if record.thumbnail_path else None,
        created_at=record.created_at,
        prompt_summary=prompt["prompt_summary"],
        prompt_summary_source=prompt["prompt_summary_source"],
        user_summary_prompt=prompt["user_summary_prompt"],
        provider_prompt=prompt["provider_prompt"],
        provider=_provider(record),
        quality_status=_quality_status(record),
        library_entity_id=record.library_entity_id,
        relation_ids=relation_ids,
        metadata=_safe_metadata(record.metadata),
    )


def _version_view(
    workflow: WorkflowV2,
    record: WorkflowAssetVersionV2,
    state: WorkflowAssetStateV2,
    relation: WorkflowAssetRelationV2 | None,
) -> WorkflowAssetVersionViewV2:
    semantic_type = _normalize_semantic_type(record.semantic_type or "", record.media_type)
    prompt = _prompt_fields(record)
    node_id = relation.target_node_id if relation and relation.target_node_id else record.node_id
    item_id = relation.target_item_id if relation and relation.target_item_id else record.item_id
    slot_id = relation.target_slot_id if relation and relation.target_slot_id else record.slot_id
    slot = _find_slot(workflow, slot_id)
    owner = _owner_fields(
        workflow,
        node_id,
        item_id,
        slot_id,
        slot.slot_type if slot else record.semantic_type or "",
        semantic_type,
    )
    return WorkflowAssetVersionViewV2(
        asset_id=record.asset_id,
        version_id=record.version_id,
        state=state,
        media_type=record.media_type,
        semantic_type=semantic_type,
        locator=asset_locator(record.asset_id, record.version_id),
        owner_type=owner["owner_type"],
        owner_node_id=owner["owner_node_id"],
        owner_item_id=owner["owner_item_id"],
        owner_slot_id=owner["owner_slot_id"],
        owner_display_name=owner["owner_display_name"],
        display_name=_display_name(record, semantic_type),
        public_url=record.public_url or f"/media/{record.file_path}",
        thumbnail_url=f"/media/{record.thumbnail_path}" if record.thumbnail_path else None,
        created_at=record.created_at,
        prompt_summary=prompt["prompt_summary"],
        prompt_summary_source=prompt["prompt_summary_source"],
        user_summary_prompt=prompt["user_summary_prompt"],
        provider_prompt=prompt["provider_prompt"],
        provider=_provider(record),
        quality_status=_quality_status(record),
        quality_issues=list(
            record.metadata.get("quality_gate_result", {}).get("issues", [])
            if isinstance(record.metadata.get("quality_gate_result"), dict)
            else []
        ),
    )


def _state_from_relation(relation: WorkflowAssetRelationV2) -> WorkflowAssetStateV2 | None:
    return {
        "selected_for_slot": "selected",
        "working_version_for_slot": "working",
        "history_version_for_slot": "history",
        "reference_for_slot": "reference",
        "reference_for_item": "reference",
        "absorbed_into": "reference",
        "available_for_composition": "reference",
        "selected_for_timeline": "reference",
        "implicit_reference_for_slot": "implicit_reference",
    }.get(relation.relation_type)


def _ownerless_asset_view(
    workflow: WorkflowV2,
    record: WorkflowAssetVersionV2,
    state: WorkflowAssetStateV2,
) -> WorkflowAssetViewV2:
    semantic_type = _normalize_semantic_type(record.semantic_type or "", record.media_type)
    prompt = _prompt_fields(record)
    return WorkflowAssetViewV2(
        asset_id=record.asset_id,
        version_id=record.version_id,
        workflow_id=workflow.workflow_id,
        node_id=None,
        item_id=None,
        slot_id=None,
        media_type=record.media_type,
        semantic_type=semantic_type,
        source_type=record.source_type,
        state=state,
        locator=asset_locator(record.asset_id, record.version_id),
        owner_type=None,
        owner_node_id=None,
        owner_item_id=None,
        owner_slot_id=None,
        owner_display_name=None,
        display_name=_display_name(record, semantic_type),
        public_url=record.public_url or f"/media/{record.file_path}",
        thumbnail_url=f"/media/{record.thumbnail_path}" if record.thumbnail_path else None,
        created_at=record.created_at,
        prompt_summary=prompt["prompt_summary"],
        prompt_summary_source=prompt["prompt_summary_source"],
        user_summary_prompt=prompt["user_summary_prompt"],
        provider_prompt=prompt["provider_prompt"],
        provider=_provider(record),
        quality_status=_quality_status(record),
        library_entity_id=record.library_entity_id,
        relation_ids=[],
        metadata=_safe_metadata(record.metadata),
    )


def _dedupe_rows(rows: list[WorkflowAssetViewV2]) -> list[WorkflowAssetViewV2]:
    deduped: dict[tuple[str, str, str | None, str], WorkflowAssetViewV2] = {}
    for row in rows:
        key = (row.asset_id, row.version_id, row.slot_id, row.state)
        if key not in deduped:
            deduped[key] = row
            continue
        existing = deduped[key]
        deduped[key] = existing.model_copy(
            update={
                "relation_ids": list(dict.fromkeys([*existing.relation_ids, *row.relation_ids]))
            }
        )
    return sorted(
        deduped.values(),
        key=lambda row: (row.created_at or "", row.node_id or "", row.slot_id or "", row.state),
    )


def _prompt_fields(record: WorkflowAssetVersionV2) -> dict[str, Any]:
    metadata = record.metadata
    prompt_snapshot = record.prompt_snapshot
    provider_payload = record.provider_payload_snapshot
    user_summary = _first_string(metadata, "user_summary_prompt")
    prompt_source = _first_string(metadata, "prompt_summary_source") or "system"
    if prompt_source not in {"user", "system", "agent", "provider"}:
        prompt_source = "system"
    provider_prompt = (
        _first_string(metadata, "provider_prompt")
        or _first_string(provider_payload, "provider_prompt")
        or _first_string(prompt_snapshot, "provider_prompt")
    )
    prompt_summary = (
        _first_string(metadata, "prompt_summary")
        or user_summary
        or _first_string(prompt_snapshot, "summary_prompt")
        or provider_prompt
    )
    return {
        "prompt_summary": prompt_summary or None,
        "prompt_summary_source": prompt_source,
        "user_summary_prompt": user_summary or None,
        "provider_prompt": provider_prompt or None,
    }


def _provider(record: WorkflowAssetVersionV2) -> str | None:
    value = _first_string(record.metadata, "provider")
    if value:
        return value
    return _first_string(record.provider_payload_snapshot, "provider") or None


def _quality_status(record: WorkflowAssetVersionV2) -> str:
    quality = record.metadata.get("quality_gate_result")
    if isinstance(quality, dict):
        value = quality.get("status")
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _display_name(record: WorkflowAssetVersionV2, semantic_type: str) -> str:
    value = _first_string(record.metadata, "display_name")
    if value and not _contains_cjk(value):
        return value
    return _DISPLAY_NAME_BY_SEMANTIC.get(semantic_type, "Workflow asset")


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in {"source_asset", "raw_response", "base64", "bytes"}
    }


def _normalize_semantic_type(
    slot_or_semantic: str, media_type: str | None = None
) -> WorkflowAssetSemanticTypeV2:
    value = slot_or_semantic
    if value.startswith("shot_cell_"):
        return "shot_cell_image"
    mapping = {
        "product_reference": "product_reference",
        "style_reference": "style_reference",
        "generic_reference": "generic_reference",
        "character_reference": "character_reference",
        "scene_reference": "scene_reference",
        "audio_reference": "audio_reference",
        "product_main_image": "product_main",
        "product_main": "product_main",
        "product_multi_view_grid": "product_multi_view",
        "product_multi_view": "product_multi_view",
        "character_main_image": "character_main",
        "character_main": "character_main",
        "character_three_view": "character_three_view",
        "scene_main_image": "scene_main",
        "scene_main": "scene_main",
        "scene_multi_view_grid": "scene_multi_view",
        "scene_multi_view": "scene_multi_view",
        "shot_cell_image": "shot_cell_image",
        "shot_video_segment": "shot_video_segment",
        "bgm_audio": "bgm",
        "bgm": "bgm",
        "final_video": "final_video",
        "free_image": "free_image",
        "free_video": "free_video",
        "free_audio": "free_audio",
    }
    if value == "free_output":
        return {
            "video": "free_video",
            "audio": "free_audio",
        }.get(media_type or "", "free_image")
    return mapping.get(value, "free_image")


def _owner_type(
    node_id: str | None,
    slot_type: str,
    semantic_type: str,
) -> str:
    if node_id == "product-generation" or semantic_type.startswith("product_"):
        return "product"
    if semantic_type == "product_reference":
        return "product"
    if node_id == "character-generation" or semantic_type.startswith("character_"):
        return "character"
    if semantic_type == "character_reference":
        return "character"
    if node_id == "scene-generation" or semantic_type.startswith("scene_"):
        return "scene"
    if semantic_type == "scene_reference":
        return "scene"
    if node_id == "storyboard" or semantic_type.startswith("shot_"):
        return "storyboard"
    if node_id == "bgm" or semantic_type == "bgm":
        return "bgm"
    if node_id == "final-composition" or semantic_type == "final_video":
        return "final_composition"
    if slot_type == "free_output" or semantic_type.startswith("free_"):
        return "free"
    return "free"


def _owner_fields(
    workflow: WorkflowV2,
    node_id: str | None,
    item_id: str | None,
    slot_id: str | None,
    slot_type: str,
    semantic_type: str,
) -> dict[str, str | None]:
    if not node_id and not item_id and not slot_id:
        return {
            "owner_type": None,
            "owner_node_id": None,
            "owner_item_id": None,
            "owner_slot_id": None,
            "owner_display_name": None,
        }
    item = _find_item_any_node(workflow, item_id)
    node = _find_node(workflow, node_id)
    return {
        "owner_type": _owner_type(node_id, slot_type, semantic_type),
        "owner_node_id": node_id,
        "owner_item_id": item_id,
        "owner_slot_id": slot_id,
        "owner_display_name": item.display_name if item else (node.title if node else None),
    }


def _workflow_slots(workflow: WorkflowV2) -> list[WorkflowSlotV2]:
    return [slot for node in workflow.nodes for item in node.items for slot in item.slots]


def _find_node(workflow: WorkflowV2, node_id: str | None):
    if not node_id:
        return None
    return next((node for node in workflow.nodes if node.node_id == node_id), None)


def _find_item_any_node(workflow: WorkflowV2, item_id: str | None):
    if not item_id:
        return None
    for node in workflow.nodes:
        for item in node.items:
            if item.item_id == item_id:
                return item
    return None


def _find_slot(workflow: WorkflowV2, slot_id: str | None) -> WorkflowSlotV2 | None:
    if not slot_id:
        return None
    return next((slot for slot in _workflow_slots(workflow) if slot.slot_id == slot_id), None)


def _find_item(workflow: WorkflowV2, node_id: str, item_id: str | None):
    if not item_id:
        return None
    node = _find_node(workflow, node_id)
    if node is None:
        return None
    return next((item for item in node.items if item.item_id == item_id), None)


def _find_slot_by_type(workflow: WorkflowV2, slot_type: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in _workflow_slots(workflow) if slot.slot_type == slot_type), None)


def _slot_by_type(item, slot_type: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in item.slots if slot.slot_type == slot_type), None)


def _storyboard_items(workflow: WorkflowV2):
    node = _find_node(workflow, "storyboard")
    if node is None:
        return []
    return sorted(
        [item for item in node.items if item.lifecycle_state == "active"],
        key=lambda item: item.shot_index or 0,
    )


def _shot_has_selected_cells(item) -> bool:
    return any(
        slot.selected_asset_id for slot in item.slots if slot.slot_type.startswith("shot_cell_")
    )


def _downstream_outdated_slots(
    workflow: WorkflowV2,
    source_slot: WorkflowSlotV2,
) -> list[WorkflowSlotV2]:
    targets: list[WorkflowSlotV2] = []
    source_item = _find_item(workflow, source_slot.node_id, source_slot.item_id)
    if source_slot.slot_type in {
        "product_main_image",
        "character_main_image",
        "scene_main_image",
    }:
        companion_slot_type = {
            "product_main_image": "product_multi_view_grid",
            "character_main_image": "character_three_view",
            "scene_main_image": "scene_multi_view_grid",
        }[source_slot.slot_type]
        if source_item is not None:
            companion = _slot_by_type(source_item, companion_slot_type)
            if companion is not None:
                targets.append(companion)
        for shot in _storyboard_items(workflow):
            targets.extend(slot for slot in shot.slots if slot.slot_type.startswith("shot_cell_"))
            if _shot_has_selected_cells(shot):
                video_slot = _slot_by_type(shot, "shot_video_segment")
                if video_slot is not None:
                    targets.append(video_slot)
    elif source_slot.slot_type in {
        "product_multi_view_grid",
        "character_three_view",
        "scene_multi_view_grid",
    }:
        for shot in _storyboard_items(workflow):
            targets.extend(slot for slot in shot.slots if slot.slot_type.startswith("shot_cell_"))
            if _shot_has_selected_cells(shot):
                video_slot = _slot_by_type(shot, "shot_video_segment")
                if video_slot is not None:
                    targets.append(video_slot)
    elif source_slot.slot_type.startswith("shot_cell_"):
        if source_item is not None:
            video_slot = _slot_by_type(source_item, "shot_video_segment")
            if video_slot is not None:
                targets.append(video_slot)
    elif source_slot.slot_type in {"shot_video_segment", "bgm_audio"}:
        final_slot = _find_slot_by_type(workflow, "final_video")
        if final_slot is not None:
            targets.append(final_slot)

    deduped: list[WorkflowSlotV2] = []
    seen_slot_ids: set[str] = set()
    for slot in targets:
        if slot.slot_id == source_slot.slot_id or slot.slot_id in seen_slot_ids:
            continue
        seen_slot_ids.add(slot.slot_id)
        deduped.append(slot)
    return deduped


def _resolve_target_slot(
    workflow: WorkflowV2,
    node_id: str,
    item_id: str | None,
    slot_id: str | None,
) -> WorkflowSlotV2 | None:
    if slot_id:
        return _find_slot(workflow, slot_id)
    for node in workflow.nodes:
        if node.node_id != node_id:
            continue
        for item in node.items:
            if item_id is not None and item.item_id != item_id:
                continue
            return next((slot for slot in item.slots if slot.required), None)
    return None


def _reference_role_compatible(role: str, media_type: str) -> bool:
    allowed = {
        "style": {"image", "video"},
        "identity": {"image"},
        "character": {"image", "video"},
        "product": {"image", "video"},
        "scene": {"image", "video"},
        "composition": {"image", "video", "audio"},
        "motion": {"video", "image"},
        "audio": {"audio"},
    }
    return media_type in allowed.get(role, set())


def _slot_reference_media_compatible(slot: WorkflowSlotV2, media_type: str) -> bool:
    if slot.media_type == "audio":
        return media_type == "audio"
    if slot.media_type == "video":
        return media_type in {"image", "video"}
    if slot.media_type == "image":
        return media_type == "image"
    return False


def _default_reference_role_for_slot(slot: WorkflowSlotV2) -> str:
    if slot.node_id == "product-generation":
        return "product"
    if slot.node_id == "character-generation":
        return "character"
    if slot.node_id == "scene-generation":
        return "scene"
    if slot.node_id == "bgm":
        return "audio"
    if slot.slot_type == "final_video":
        return "composition"
    if slot.media_type == "video":
        return "motion"
    return "style"


def _semantic_type_for_reference(role: str, slot: WorkflowSlotV2) -> str:
    if role == "product":
        return "product_reference"
    if role in {"character", "identity"}:
        return "character_reference"
    if role == "scene":
        return "scene_reference"
    if role == "style":
        return "style_reference"
    if role == "audio":
        return "audio_reference"
    if role in {"composition", "motion"}:
        return _normalize_semantic_type(slot.slot_type, slot.media_type)
    return "generic_reference"


def _media_type_hint(file: UploadFile) -> str:
    content_type = (file.content_type or "").lower()
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    suffix = Path(file.filename or "").suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".mp3", ".wav", ".m4a"}:
        return "audio"
    raise V2WorkflowAssetError("unsupported_upload_media_type")


def _library_asset_media_type(asset: LibraryAsset) -> str:
    media_type = (
        (asset.media_type or asset.asset_type or asset.type or asset.kind or "").strip().lower()
    )
    if media_type in {"image", "video", "audio"}:
        return media_type
    mime_type = (asset.mime_type or "").lower()
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    suffix = Path(asset.uri).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".mp3", ".wav", ".m4a"}:
        return "audio"
    raise V2WorkflowAssetError("unsupported_library_asset_media_type")


def _library_asset_source_path(data_dir: Path, asset: LibraryAsset) -> Path:
    raw_path = asset.uri.strip()
    if not raw_path:
        raise V2WorkflowAssetError("asset_library_asset_not_found")
    if raw_path.startswith(("http://", "https://")):
        raise V2WorkflowAssetError("remote_reference_registration_not_supported")
    path = Path(raw_path)
    candidate = path if path.is_absolute() else data_dir / path
    try:
        resolved = candidate.resolve()
        resolved.relative_to(data_dir.resolve())
    except ValueError as exc:
        raise V2WorkflowAssetError("v2_data_boundary_violation", str(exc)) from exc
    if not resolved.exists():
        raise V2WorkflowAssetError("asset_not_found")
    return resolved


def _library_asset_suffix(source_path: Path, media_type: str) -> str:
    suffix = source_path.suffix.lower()
    if suffix:
        return suffix
    return {"image": ".png", "video": ".mp4", "audio": ".mp3"}.get(media_type, ".bin")


def _absorb_compatible(record: WorkflowAssetVersionV2, slot: WorkflowSlotV2) -> bool:
    if record.media_type == "image":
        return slot.media_type == "image"
    if record.media_type == "video":
        return slot.slot_type in {"shot_video_segment", "final_video", "free_output"}
    if record.media_type == "audio":
        return slot.slot_type in {"bgm_audio", "free_output"}
    return False


def _default_reference_role(media_type: str) -> str:
    return {"audio": "audio", "video": "motion"}.get(media_type, "style")


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _append_unique_metadata(metadata: dict[str, Any], key: str, value: str) -> None:
    values = [str(item) for item in metadata.get(key, []) if str(item)]
    if value not in values:
        values.append(value)
    metadata[key] = values


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _record_from_slot_relations(
    asset_store: V2AssetStoreService,
    *,
    workflow_id: str,
    slot_id: str,
    version_id: str,
) -> WorkflowAssetVersionV2 | None:
    for relation in asset_store.list_relations(
        target_workflow_id=workflow_id,
        target_slot_id=slot_id,
    ):
        if relation.metadata.get("version_id") != version_id:
            continue
        record = asset_store.load_asset_version(relation.source_asset_id, version_id)
        if record is not None:
            return record
    return None


def uuid4_hex() -> str:
    return uuid4().hex[:12]


_DISPLAY_NAME_BY_SEMANTIC = {
    "product_reference": "Product reference",
    "style_reference": "Style reference",
    "generic_reference": "Generic reference",
    "character_reference": "Character reference",
    "scene_reference": "Scene reference",
    "audio_reference": "Audio reference",
    "product_main": "Product main image",
    "product_multi_view": "Product multi-view image",
    "character_main": "Character main image",
    "character_three_view": "Character three-view image",
    "scene_main": "Scene main image",
    "scene_multi_view": "Scene multi-view image",
    "shot_cell_image": "Storyboard cell image",
    "shot_video_segment": "Storyboard video segment",
    "bgm": "Background music",
    "final_video": "Final video",
    "free_image": "Free image",
    "free_video": "Free video",
    "free_audio": "Free audio",
}
