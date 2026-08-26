"""Atomic reuse of terminal Editing outputs as source-only Canvas videos."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.agent_canvas_repository import (
    AgentCanvasWorkflowRepository,
    _advance_workflow_revision,
    _binding_values,
    _load_idempotency,
    _node_values,
    _require_workflow_revision,
    _store_idempotency,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasEditingExportCommitRow,
    AgentCanvasEditingExportRow,
    AgentCanvasNodeRow,
    AgentCanvasBindingRow,
    AgentCanvasWorkflowRow,
    AssetVersionRow,
)
from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
)
from app.schemas.agent_canvas_editing_output_reuse import (
    EditingExportOutputReuseRequestV2,
    EditingExportOutputReuseResponseV2,
)
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.v2_storage_adapter import StorageAdapter
from app.schemas.v2_persistence import V2EventInsert


class EditingExportOutputReuseService:
    """Publish one immutable Editing output as a downstream source node."""

    def __init__(
        self,
        database: V2Database,
        workflows: AgentCanvasWorkflowRepository,
        assets: AgentCanvasAssetService,
        events: EventRepository,
        *,
        data_dir: Path,
        connection_policy: AgentCanvasConnectionPolicyService,
    ) -> None:
        self._database = database
        self._workflows = workflows
        self._assets = assets
        self._events = events
        self._storage = StorageAdapter(data_dir)
        self._connection_policy = connection_policy

    def import_export(
        self,
        workflow_id: str,
        editing_node_id: str,
        request: EditingExportOutputReuseRequestV2,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> EditingExportOutputReuseResponseV2:
        if not idempotency_key:
            raise _error("idempotency_key_required", "Idempotency-Key is required.")
        operation = f"agent_canvas_editing_output_reuse:{workflow_id}"
        fingerprint = sha256(
            json.dumps(
                {
                    "workflow_id": workflow_id,
                    "editing_node_id": editing_node_id,
                    "request": request.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        now = datetime.now(timezone.utc)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _load_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=fingerprint,
                    )
                    if replay is not None:
                        connection.commit()
                        return EditingExportOutputReuseResponseV2.model_validate_json(
                            replay
                        ).model_copy(update={"replayed": True})

                    current_revision = _require_workflow_revision(
                        connection, workflow_id, expected_revision
                    )
                    export, version_id = self._validate_export(
                        connection,
                        workflow_id=workflow_id,
                        editing_node_id=editing_node_id,
                        export_id=request.export_id,
                    )
                    version = self._validate_version(
                        connection,
                        asset_id=str(export["output_asset_id"]),
                        version_id=version_id,
                    )
                    asset = self._assets.resolve_asset_version(
                        str(export["output_asset_id"]), version_id
                    )
                    source = self._workflows.get_node(workflow_id, editing_node_id)
                    if source.node_type != "editing":
                        raise _error(
                            "editing_export_import_conflict",
                            "Editing output reuse requires an Editing source node.",
                        )
                    policy = self._connection_policy.require(
                        source_node_type=source.node_type,
                        target_node_type="video",
                        input_role="video_reference",
                    )
                    if policy.input_role != "video_reference":
                        raise _error(
                            "editing_export_import_conflict",
                            "Editing output reuse requires the video_reference binding role.",
                        )
                    node_id = f"node_{uuid4().hex}"
                    binding_id = f"binding_{uuid4().hex}"
                    node = CanvasNodeV2(
                        node_id=node_id,
                        workflow_id=workflow_id,
                        node_type="video",
                        creative_role="general_video",
                        role_contract_version="ad-media-role-v2",
                        title=request.title or asset.display_name,
                        status="ready",
                        execution_mode="source_only",
                        summary_prompt=None,
                        generation_prompt=None,
                        structured_content={},
                        output_asset_id=asset.asset_id,
                        metadata={
                            "source_export_id": request.export_id,
                            "source_asset_id": asset.asset_id,
                            "source_version_id": version_id,
                            "source_asset_sha256": str(version["sha256"]),
                        },
                        position=request.position,
                        revision=1,
                        prompt_preparation=NodePromptPreparationV1.legacy_ready(),
                        created_at=now,
                        updated_at=now,
                    )
                    binding = CanvasBindingV2(
                        binding_id=binding_id,
                        workflow_id=workflow_id,
                        source=CanvasBindingSourceNodeV2(source_node_id=editing_node_id),
                        target_node_id=node_id,
                        input_role="video_reference",
                        required=True,
                        enabled=True,
                        order=0,
                        metadata={
                            "origin": "editing_export",
                            "export_id": request.export_id,
                            "asset_id": asset.asset_id,
                            "version_id": version_id,
                            "sha256": str(version["sha256"]),
                        },
                        created_at=now,
                        updated_at=now,
                    )
                    connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    connection.execute(
                        insert(AgentCanvasBindingRow).values(**_binding_values(binding))
                    )
                    _advance_workflow_revision(
                        connection,
                        workflow_id=workflow_id,
                        current_revision=current_revision,
                        updated_at=now.isoformat(),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=node_id,
                            event_type="canvas_node_created",
                            created_at=now.isoformat(),
                            payload={
                                "node_type": "video",
                                "execution_mode": "source_only",
                                "asset_id": asset.asset_id,
                                "version_id": version_id,
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=node_id,
                            binding_id=binding_id,
                            event_type="canvas_binding_created",
                            created_at=now.isoformat(),
                            payload={
                                "input_role": "video_reference",
                                "source_node_id": editing_node_id,
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=node_id,
                            asset_id=asset.asset_id,
                            event_type="editing_export_imported_to_canvas",
                            created_at=now.isoformat(),
                            payload={
                                "export_id": request.export_id,
                                "asset_id": asset.asset_id,
                                "version_id": version_id,
                                "sha256": str(version["sha256"]),
                            },
                        ),
                    )
                    revision_event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="workflow_revision_created",
                            created_at=now.isoformat(),
                            payload={"revision": current_revision + 1},
                        ),
                    )
                    layout_revision = int(
                        connection.execute(
                            select(AgentCanvasWorkflowRow.layout_revision).where(
                                AgentCanvasWorkflowRow.workflow_id == workflow_id
                            )
                        ).scalar_one()
                    )
                    response = EditingExportOutputReuseResponseV2(
                        workflow_id=workflow_id,
                        revision=current_revision + 1,
                        layout_revision=layout_revision,
                        node=node,
                        binding=binding,
                        asset=asset,
                        events_cursor=revision_event.seq,
                        replayed=False,
                    )
                    _store_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=fingerprint,
                        response_json=response.model_dump_json(),
                        created_at=now.isoformat(),
                    )
                    connection.commit()
                    return response
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error(
                "editing_export_import_conflict",
                "Editing output reuse conflicts with existing Canvas state.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "editing_export_import_conflict",
                "Editing output reuse could not be persisted.",
            ) from error

    def _validate_export(self, connection, *, workflow_id, editing_node_id, export_id):
        export = (
            connection.execute(
                select(AgentCanvasEditingExportRow).where(
                    AgentCanvasEditingExportRow.export_id == export_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if export is None:
            raise _error("editing_export_not_found", "Editing export was not found.")
        if str(export["workflow_id"]) != workflow_id or str(export["node_id"]) != editing_node_id:
            raise _error(
                "editing_export_workflow_mismatch",
                "Editing export does not belong to the requested Workflow and Node.",
            )
        if str(export["status"]) != "completed" or export["output_asset_id"] is None:
            raise _error("editing_export_not_ready", "Editing export is not terminal and ready.")
        receipt = connection.execute(
            select(AgentCanvasEditingExportCommitRow.version_id).where(
                AgentCanvasEditingExportCommitRow.export_id == export_id
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise _error("editing_export_not_ready", "Editing export has no terminal receipt.")
        return export, str(receipt)

    def _validate_version(self, connection, *, asset_id: str, version_id: str):
        version = (
            connection.execute(
                select(AssetVersionRow).where(
                    AssetVersionRow.asset_id == asset_id,
                    AssetVersionRow.version_id == version_id,
                    AssetVersionRow.status == "ready",
                )
            )
            .mappings()
            .one_or_none()
        )
        if version is None or not self._storage.file_exists(str(version["storage_key"])):
            raise _error(
                "editing_export_asset_unreadable",
                "Editing export AssetVersion is unreadable.",
            )
        return version


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing_output_reuse")
