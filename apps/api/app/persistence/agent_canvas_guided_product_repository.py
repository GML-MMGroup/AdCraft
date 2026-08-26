"""SQLite authority for typed Product source-only materialization."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.agent_canvas_repository import (
    AgentCanvasWorkflowRepository,
    _advance_workflow_revision,
    _idempotency_conflict_error,
    _load_idempotency,
    _node_values,
    _require_workflow_revision,
    _store_idempotency,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasGuidanceSessionRow, AgentCanvasNodeRow
from app.schemas.agent_canvas import CanvasNodeV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_guided_product import (
    GuidedProductInputCommitReceiptV1,
    GuidedProductInputCommitRequestV1,
    GuidedProductInputCommitResponseV1,
)
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasGuidedProductRepository:
    """Commit source-only Product Nodes and receipts in one SQLite transaction."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        events: EventRepository,
    ) -> None:
        self._workflows = workflows
        self._events = events

    def commit(
        self,
        *,
        node: CanvasNodeV2,
        request: GuidedProductInputCommitRequestV1,
        idempotency_key: str,
        request_digest: str,
        expected_workflow_revision: int,
        guidance_revision: int,
        compiled_asset: ProjectAssetSummaryV2 | None,
        output_asset_id: str,
        output_version_id: str,
        provenance_digest: str | None,
    ) -> GuidedProductInputCommitResponseV1:
        operation = f"guided_product_input:{node.workflow_id}"
        database = self._workflows.database
        try:
            with database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _load_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_digest,
                    )
                    if replay is not None:
                        connection.commit()
                        return GuidedProductInputCommitResponseV1.model_validate_json(
                            replay
                        ).model_copy(update={"replayed": True})

                    current_revision = _require_workflow_revision(
                        connection,
                        node.workflow_id,
                        expected_workflow_revision,
                    )
                    guidance_revision_row = connection.execute(
                        select(AgentCanvasGuidanceSessionRow.revision).where(
                            AgentCanvasGuidanceSessionRow.workflow_id == node.workflow_id
                        )
                    ).scalar_one_or_none()
                    current_guidance_revision = (
                        int(guidance_revision_row) if guidance_revision_row is not None else 1
                    )
                    if current_guidance_revision != guidance_revision:
                        raise V2PersistenceError(
                            "guidance_revision_conflict",
                            "Guidance session revision does not match the current revision.",
                            stage="guided_product_repository",
                        )
                    existing = connection.execute(
                        select(AgentCanvasNodeRow.node_id).where(
                            AgentCanvasNodeRow.workflow_id == node.workflow_id,
                            AgentCanvasNodeRow.creative_role == "product",
                            AgentCanvasNodeRow.metadata_json.contains(
                                f'"source_input_kind":"{request.input_kind}"'
                            ),
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        raise V2PersistenceError(
                            "guided_product_input_already_committed",
                            "This Product input kind already has a canonical source Node.",
                            stage="guided_product_repository",
                        )
                    connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    _advance_workflow_revision(
                        connection,
                        workflow_id=node.workflow_id,
                        current_revision=current_revision,
                        updated_at=node.updated_at.isoformat(),
                    )
                    next_revision = current_revision + 1
                    operation_id = f"op_{uuid4().hex}"
                    source_event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            node_id=node.node_id,
                            asset_id=output_asset_id,
                            version_id=output_version_id,
                            event_type="guided_product_source_materialized",
                            transition_key=f"guided-product:{node.workflow_id}:{request.input_kind}",
                            created_at=node.updated_at.isoformat(),
                            payload={
                                "operation_id": operation_id,
                                "input_kind": request.input_kind,
                                "node_revision": node.revision,
                                "workflow_revision": next_revision,
                                "provenance_digest": provenance_digest,
                            },
                        ),
                    )
                    receipt = GuidedProductInputCommitReceiptV1(
                        operation_id=operation_id,
                        request_digest=request_digest,
                        workflow_id=node.workflow_id,
                        input_kind=request.input_kind,
                        node_id=node.node_id,
                        asset_id=output_asset_id,
                        version_id=output_version_id,
                        compiled_asset_id=(compiled_asset.asset_id if compiled_asset else None),
                        compiled_version_id=(compiled_asset.version_id if compiled_asset else None),
                        provenance_digest=provenance_digest,
                        workflow_revision=next_revision,
                        guidance_revision=guidance_revision,
                        events_cursor=source_event.seq,
                        committed_at=datetime.now(timezone.utc),
                    )
                    response = GuidedProductInputCommitResponseV1(
                        workflow_id=node.workflow_id,
                        workflow_revision=next_revision,
                        guidance_revision=guidance_revision,
                        input_kind=request.input_kind,
                        node=node,
                        compiled_asset=compiled_asset,
                        receipt=receipt,
                        events_cursor=source_event.seq,
                    )
                    _store_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_digest,
                        response_json=response.model_dump_json(),
                        created_at=node.updated_at.isoformat(),
                    )
                    connection.commit()
                    return response
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _idempotency_conflict_error() from error
        except SQLAlchemyError as error:
            raise V2PersistenceError(
                "guided_product_persistence_unavailable",
                "Product source materialization could not be persisted.",
                stage="guided_product_repository",
            ) from error

    def lookup_replay(
        self,
        *,
        workflow_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> GuidedProductInputCommitResponseV1 | None:
        """Read one exact typed commit receipt before expensive compilation."""

        operation = f"guided_product_input:{workflow_id}"
        with self._workflows.database.engine.connect() as connection:
            replay = _load_idempotency(
                connection,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=request_digest,
            )
        if replay is None:
            return None
        return GuidedProductInputCommitResponseV1.model_validate_json(replay).model_copy(
            update={"replayed": True}
        )


def request_digest(
    workflow_id: str,
    request: GuidedProductInputCommitRequestV1,
    expected_workflow_revision: int,
) -> str:
    payload = {
        "contract": "guided-product-input-v1",
        "workflow_id": workflow_id,
        "workflow_revision": expected_workflow_revision,
        **request.model_dump(mode="json"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
