"""Atomic SQLite-backed reference selections for V2 workflow slots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_asset_library import (
    AssetBindingCreate,
    AssetBindingV2,
    AssetEntityReferenceSelectionV2,
    AssetVersionReferenceSelectionV2,
    AttachReferenceSelectionsRequestV2,
    ReferenceSelectionMutationResponseV2,
)
from app.schemas.workflow_v2 import WorkflowSlotV2, WorkflowV2
from app.services.v2_runtime_events import V2RuntimeEventService
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime


class V2ReferenceSelectionError(RuntimeError):
    """Typed failure suitable for the V2 reference-selection API."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _BindingCandidate:
    asset_id: str
    version_id: str
    source_entity_id: str | None


class V2ReferenceSelectionService:
    """Attach and remove immutable library versions without touching their media."""

    def __init__(self, data_dir: Path) -> None:
        self._runtime = create_workflow_authoring_runtime(data_dir)
        self._repository = V2AssetLibraryRepository(self._runtime.database)
        self._events = V2RuntimeEventService(data_dir)

    def attach(
        self,
        workflow_id: str,
        slot_id: str,
        request: AttachReferenceSelectionsRequestV2,
        *,
        expected_state_version: int,
    ) -> ReferenceSelectionMutationResponseV2:
        workflow = self._load_expected_workflow(workflow_id, expected_state_version)
        slot = _slot_by_id(workflow, slot_id)
        candidates = self._resolve_candidates(request)
        existing = self._repository.list_bindings(
            workflow_id=workflow_id,
            target_slot_id=slot_id,
            binding_type="reference_for_slot",
        )
        new_candidates = [
            candidate
            for candidate in candidates
            if not _binding_exists(existing, candidate, request)
        ]
        if not new_candidates:
            return self._response(workflow, selection_group_id=None, bindings=existing, events=())

        selection_group_id = f"rsel_{uuid4().hex}"
        start_order = max((binding.sort_order for binding in existing), default=-1) + 1
        pending = tuple(
            AssetBindingCreate(
                binding_id=f"bind_{uuid4().hex}",
                selection_group_id=selection_group_id,
                binding_type="reference_for_slot",
                workflow_id=workflow_id,
                target_node_id=slot.node_id,
                target_item_id=slot.item_id,
                target_slot_id=slot.slot_id,
                source_entity_id=candidate.source_entity_id,
                asset_id=candidate.asset_id,
                version_id=candidate.version_id,
                reference_role=request.reference_role,
                use_as_prompt=request.use_as_prompt,
                sort_order=start_order + index,
                metadata={"source": "v2_reference_selection"},
            )
            for index, candidate in enumerate(new_candidates)
        )
        try:
            with self._runtime.database.engine.begin() as connection:
                for binding in pending:
                    self._repository.create_binding(binding, connection=connection)
        except V2PersistenceError as error:
            raise _selection_error(error) from error

        try:
            slot.explicit_reference_ids = list(
                dict.fromkeys(
                    [*slot.explicit_reference_ids, *(binding.asset_id for binding in pending)]
                )
            )
            workflow = self._runtime.service.commit_semantic_workflow(
                workflow,
                expected_version=expected_state_version,
                source="reference_change",
            )
        except V2PersistenceError as error:
            for binding in pending:
                self._repository.remove_binding(binding.binding_id)
            raise _selection_error(error) from error

        current_bindings = self._repository.list_bindings(
            workflow_id=workflow_id,
            target_slot_id=slot_id,
            binding_type="reference_for_slot",
        )
        events = tuple(
            self._events.append_event(
                workflow_id,
                "reference_attached",
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                asset_id=binding.asset_id,
                version_id=binding.version_id,
                payload={
                    "binding_id": binding.binding_id,
                    "relation_id": binding.binding_id,
                    "selection_group_id": binding.selection_group_id,
                    "reference_role": binding.reference_role,
                },
            )
            for binding in pending
        )
        snapshot_event = self._events.append_event(
            workflow_id,
            "runtime_snapshot_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={"source": "v2_reference_selection", "binding_count": len(current_bindings)},
        )
        return self._response(
            workflow,
            selection_group_id=selection_group_id,
            bindings=current_bindings,
            events=(*events, snapshot_event),
        )

    def is_binding(self, workflow_id: str, binding_id: str) -> bool:
        binding = self._repository.get_binding(binding_id)
        return binding is not None and binding.workflow_id == workflow_id

    def remove(
        self,
        workflow_id: str,
        binding_id: str,
        *,
        expected_state_version: int,
    ) -> ReferenceSelectionMutationResponseV2:
        workflow = self._load_expected_workflow(workflow_id, expected_state_version)
        binding = self._repository.get_binding(binding_id)
        if binding is None or binding.workflow_id != workflow_id:
            raise V2ReferenceSelectionError(
                "asset_binding_not_found", "Asset binding was not found.", status_code=404
            )
        if binding.status == "removed":
            remaining = self._repository.list_bindings(
                workflow_id=workflow_id,
                target_slot_id=binding.target_slot_id,
                binding_type="reference_for_slot",
            )
            return self._response(
                workflow,
                selection_group_id=None,
                bindings=remaining,
                removed_binding_id=binding_id,
                events=(),
            )
        if not binding.target_slot_id:
            raise V2ReferenceSelectionError(
                "asset_binding_target_invalid", "Asset binding is not attached to a workflow slot."
            )
        slot = _slot_by_id(workflow, binding.target_slot_id)
        try:
            self._repository.remove_binding(binding_id)
        except V2PersistenceError as error:
            raise _selection_error(error) from error
        remaining = self._repository.list_bindings(
            workflow_id=workflow_id,
            target_slot_id=slot.slot_id,
            binding_type="reference_for_slot",
        )
        try:
            if binding.asset_id not in {item.asset_id for item in remaining}:
                slot.explicit_reference_ids = [
                    asset_id
                    for asset_id in slot.explicit_reference_ids
                    if asset_id != binding.asset_id
                ]
            workflow = self._runtime.service.commit_semantic_workflow(
                workflow,
                expected_version=expected_state_version,
                source="reference_change",
            )
        except V2PersistenceError as error:
            self._repository.restore_binding(binding_id)
            raise _selection_error(error) from error

        removed_event = self._events.append_event(
            workflow_id,
            "reference_removed",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=binding.asset_id,
            version_id=binding.version_id,
            payload={
                "binding_id": binding.binding_id,
                "relation_id": binding.binding_id,
                "selection_group_id": binding.selection_group_id,
            },
        )
        snapshot_event = self._events.append_event(
            workflow_id,
            "runtime_snapshot_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={"source": "v2_reference_selection", "binding_count": len(remaining)},
        )
        return self._response(
            workflow,
            selection_group_id=None,
            bindings=remaining,
            removed_binding_id=binding_id,
            events=(removed_event, snapshot_event),
        )

    def _load_expected_workflow(self, workflow_id: str, expected_state_version: int) -> WorkflowV2:
        try:
            workflow = self._runtime.read_model.assemble(workflow_id)
        except V2PersistenceError as error:
            raise _selection_error(error) from error
        if workflow.state_version != expected_state_version:
            raise V2ReferenceSelectionError(
                "workflow_etag_conflict",
                "The workflow has changed. Refresh and retry the reference selection.",
                status_code=412,
            )
        return workflow

    def _resolve_candidates(
        self, request: AttachReferenceSelectionsRequestV2
    ) -> tuple[_BindingCandidate, ...]:
        candidates: list[_BindingCandidate] = []
        try:
            for selection in request.selections:
                if isinstance(selection, AssetEntityReferenceSelectionV2):
                    entity = self._repository.get_entity(selection.entity_id)
                    if entity.status != "active":
                        raise V2ReferenceSelectionError(
                            "asset_entity_not_active",
                            "The selected asset entity is not available.",
                        )
                    members = [
                        member
                        for member in entity.members
                        if member.is_default_reference and member.version is not None
                    ]
                    if not members:
                        raise V2ReferenceSelectionError(
                            "asset_entity_has_no_default_reference",
                            "The selected asset entity has no default reference members.",
                            status_code=422,
                        )
                    candidates.extend(
                        _BindingCandidate(
                            asset_id=member.asset_id,
                            version_id=member.version_id,
                            source_entity_id=entity.entity_id,
                        )
                        for member in members
                    )
                    continue
                if isinstance(selection, AssetVersionReferenceSelectionV2):
                    version = self._repository.resolve_versions((selection.version_id,))[0]
                    if version.asset_id != selection.asset_id:
                        raise V2ReferenceSelectionError(
                            "asset_binding_version_mismatch",
                            "The selected asset version does not belong to the requested asset.",
                            status_code=422,
                        )
                    candidates.append(
                        _BindingCandidate(
                            asset_id=selection.asset_id,
                            version_id=selection.version_id,
                            source_entity_id=None,
                        )
                    )
        except V2PersistenceError as error:
            raise _selection_error(error) from error
        return _deduplicate_candidates(candidates)

    def _response(
        self,
        workflow: WorkflowV2,
        *,
        selection_group_id: str | None,
        bindings: tuple[AssetBindingV2, ...],
        events: tuple,
        removed_binding_id: str | None = None,
    ) -> ReferenceSelectionMutationResponseV2:
        refreshed = self._runtime.read_model.assemble(workflow.workflow_id)
        return ReferenceSelectionMutationResponseV2(
            workflow=refreshed,
            selection_group_id=selection_group_id,
            bindings=bindings,
            removed_binding_id=removed_binding_id,
            runtime=self._events.runtime_snapshot(refreshed),
            events=events,
        )


def _slot_by_id(workflow: WorkflowV2, slot_id: str) -> WorkflowSlotV2:
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                if slot.slot_id == slot_id:
                    return slot
    raise V2ReferenceSelectionError(
        "workflow_slot_not_found", "Workflow slot was not found.", status_code=404
    )


def _binding_exists(
    bindings: tuple[AssetBindingV2, ...],
    candidate: _BindingCandidate,
    request: AttachReferenceSelectionsRequestV2,
) -> bool:
    return any(
        binding.asset_id == candidate.asset_id
        and binding.version_id == candidate.version_id
        and binding.reference_role == request.reference_role
        and binding.use_as_prompt == request.use_as_prompt
        for binding in bindings
    )


def _deduplicate_candidates(candidates: list[_BindingCandidate]) -> tuple[_BindingCandidate, ...]:
    unique: dict[tuple[str, str, str | None], _BindingCandidate] = {}
    for candidate in candidates:
        unique.setdefault(
            (candidate.asset_id, candidate.version_id, candidate.source_entity_id), candidate
        )
    return tuple(unique.values())


def _selection_error(error: V2PersistenceError) -> V2ReferenceSelectionError:
    if error.code == "workflow_not_found":
        return V2ReferenceSelectionError(error.code, str(error), status_code=404)
    if error.code in {
        "asset_entity_not_found",
        "asset_version_not_found",
        "asset_binding_not_found",
    }:
        return V2ReferenceSelectionError(error.code, str(error), status_code=404)
    if error.code == "workflow_state_version_conflict":
        return V2ReferenceSelectionError("workflow_etag_conflict", str(error), status_code=412)
    return V2ReferenceSelectionError(error.code, str(error))
