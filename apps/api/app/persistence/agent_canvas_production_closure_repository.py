"""Immutable SQLite authority for guided production receipts."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal, TypeVar, cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import AgentCanvasGuidedProductionReceiptRow
from app.schemas.agent_canvas_production_closure import (
    GuidedEditingPreparationReceiptV1,
    GuidedFinalCompletionReceiptV1,
    GuidedMediaConfirmationV1,
    StoryboardFanoutPlanV1,
)


ReceiptType = Literal[
    "storyboard_fanout",
    "media_confirmation",
    "editing_preparation",
    "final_completion",
]
ReceiptModel = (
    StoryboardFanoutPlanV1
    | GuidedMediaConfirmationV1
    | GuidedEditingPreparationReceiptV1
    | GuidedFinalCompletionReceiptV1
)
ReceiptT = TypeVar("ReceiptT", bound=BaseModel)

_MODEL_BY_TYPE: dict[ReceiptType, type[BaseModel]] = {
    "storyboard_fanout": StoryboardFanoutPlanV1,
    "media_confirmation": GuidedMediaConfirmationV1,
    "editing_preparation": GuidedEditingPreparationReceiptV1,
    "final_completion": GuidedFinalCompletionReceiptV1,
}


class AgentCanvasProductionClosureRepository:
    """Persist exact guided production transitions once per logical identity."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def save_confirmation(
        self, confirmation: GuidedMediaConfirmationV1
    ) -> GuidedMediaConfirmationV1:
        return self._save("media_confirmation", confirmation)

    def save_confirmation_in_transaction(
        self,
        connection: Connection,
        confirmation: GuidedMediaConfirmationV1,
    ) -> GuidedMediaConfirmationV1:
        return self._save_in_transaction(connection, "media_confirmation", confirmation)

    def get_confirmation(self, confirmation_id: str) -> GuidedMediaConfirmationV1:
        return self._get("media_confirmation", confirmation_id, GuidedMediaConfirmationV1)

    def find_confirmation_for_source(
        self,
        *,
        workflow_id: str,
        plan_document_id: str,
        node_id: str,
        node_revision: int,
        asset_id: str,
        asset_version_id: str,
        asset_digest: str,
    ) -> GuidedMediaConfirmationV1 | None:
        """Find the immutable acceptance for one exact media source."""

        return next(
            (
                cast(GuidedMediaConfirmationV1, item)
                for item in reversed(self._list("media_confirmation", workflow_id))
                if (
                    item.plan_document_id == plan_document_id
                    and item.node_id == node_id
                    and item.node_revision == node_revision
                    and item.asset_id == asset_id
                    and item.asset_version_id == asset_version_id
                    and item.asset_digest == asset_digest
                )
            ),
            None,
        )

    def save_fanout(self, plan: StoryboardFanoutPlanV1) -> StoryboardFanoutPlanV1:
        return self._save("storyboard_fanout", plan)

    def save_fanout_in_transaction(
        self,
        connection: Connection,
        plan: StoryboardFanoutPlanV1,
    ) -> StoryboardFanoutPlanV1:
        return self._save_in_transaction(connection, "storyboard_fanout", plan)

    def get_fanout(self, fanout_plan_id: str) -> StoryboardFanoutPlanV1:
        return self._get("storyboard_fanout", fanout_plan_id, StoryboardFanoutPlanV1)

    def find_fanout_for_confirmation(
        self,
        confirmation_id: str,
    ) -> StoryboardFanoutPlanV1 | None:
        confirmation = self.get_confirmation(confirmation_id)
        return next(
            (
                cast(StoryboardFanoutPlanV1, item)
                for item in reversed(self._list("storyboard_fanout", confirmation.workflow_id))
                if item.visual_anchor_confirmation_id == confirmation_id
                or (
                    item.plan_document_id == confirmation.plan_document_id
                    and any(node.node_id == confirmation.node_id for node in item.nodes)
                )
            ),
            None,
        )

    def save_preparation(
        self, receipt: GuidedEditingPreparationReceiptV1
    ) -> GuidedEditingPreparationReceiptV1:
        return self._save("editing_preparation", receipt)

    def get_preparation(self, receipt_id: str) -> GuidedEditingPreparationReceiptV1:
        return self._get(
            "editing_preparation",
            receipt_id,
            GuidedEditingPreparationReceiptV1,
        )

    def find_preparation(
        self,
        workflow_id: str,
        plan_document_id: str,
        plan_revision: int,
    ) -> GuidedEditingPreparationReceiptV1 | None:
        return next(
            (
                cast(GuidedEditingPreparationReceiptV1, item)
                for item in self._list("editing_preparation", workflow_id)
                if item.plan_document_id == plan_document_id and item.plan_revision == plan_revision
            ),
            None,
        )

    def find_preparation_for_editing(
        self,
        workflow_id: str,
        editing_node_id: str,
    ) -> GuidedEditingPreparationReceiptV1 | None:
        return next(
            (
                cast(GuidedEditingPreparationReceiptV1, item)
                for item in reversed(self._list("editing_preparation", workflow_id))
                if item.editing_node_id == editing_node_id
            ),
            None,
        )

    def save_completion(
        self, receipt: GuidedFinalCompletionReceiptV1
    ) -> GuidedFinalCompletionReceiptV1:
        return self._save("final_completion", receipt)

    def get_completion(self, receipt_id: str) -> GuidedFinalCompletionReceiptV1:
        return self._get("final_completion", receipt_id, GuidedFinalCompletionReceiptV1)

    def find_completion_for_export(
        self,
        export_id: str,
    ) -> GuidedFinalCompletionReceiptV1 | None:
        try:
            with self._database.session_factory() as session:
                rows = session.scalars(
                    select(AgentCanvasGuidedProductionReceiptRow).where(
                        AgentCanvasGuidedProductionReceiptRow.receipt_type == "final_completion"
                    )
                ).all()
        except SQLAlchemyError as error:
            raise _error(
                "guided_production_receipt_persistence_failed",
                "Guided production receipt storage is unavailable.",
            ) from error
        for row in rows:
            receipt = GuidedFinalCompletionReceiptV1.model_validate_json(row.payload_json)
            if receipt.export_id == export_id:
                return receipt
        return None

    def list_confirmations(self, workflow_id: str) -> tuple[GuidedMediaConfirmationV1, ...]:
        return tuple(
            cast(GuidedMediaConfirmationV1, item)
            for item in self._list("media_confirmation", workflow_id)
        )

    def _save(self, receipt_type: ReceiptType, model: ReceiptT) -> ReceiptT:
        payload_json = _canonical_payload(model)
        payload_digest = sha256(payload_json.encode()).hexdigest()
        receipt_id = _receipt_id(model)
        logical_identity = str(getattr(model, "logical_identity"))
        workflow_id = str(getattr(model, "workflow_id"))
        created_at = _created_at(model)
        try:
            with self._database.session_factory.begin() as session:
                existing = session.scalar(
                    select(AgentCanvasGuidedProductionReceiptRow).where(
                        AgentCanvasGuidedProductionReceiptRow.receipt_type == receipt_type,
                        AgentCanvasGuidedProductionReceiptRow.logical_identity == logical_identity,
                    )
                )
                if existing is not None:
                    return self._replay_or_conflict(existing, payload_digest, type(model))
                session.add(
                    AgentCanvasGuidedProductionReceiptRow(
                        receipt_id=receipt_id,
                        receipt_type=receipt_type,
                        logical_identity=logical_identity,
                        workflow_id=workflow_id,
                        payload_digest=payload_digest,
                        payload_json=payload_json,
                        created_at=created_at,
                    )
                )
        except IntegrityError:
            return self._get_by_identity(
                receipt_type,
                logical_identity,
                payload_digest,
                type(model),
            )
        except SQLAlchemyError as error:
            raise _error(
                "guided_production_receipt_persistence_failed",
                "Guided production receipt storage is unavailable.",
            ) from error
        return model

    def _save_in_transaction(
        self,
        connection: Connection,
        receipt_type: ReceiptType,
        model: ReceiptT,
    ) -> ReceiptT:
        payload_json = _canonical_payload(model)
        payload_digest = sha256(payload_json.encode()).hexdigest()
        receipt_id = _receipt_id(model)
        logical_identity = str(getattr(model, "logical_identity"))
        workflow_id = str(getattr(model, "workflow_id"))
        created_at = _created_at(model)
        with Session(bind=connection) as session:
            existing = session.scalar(
                select(AgentCanvasGuidedProductionReceiptRow).where(
                    AgentCanvasGuidedProductionReceiptRow.receipt_type == receipt_type,
                    AgentCanvasGuidedProductionReceiptRow.logical_identity == logical_identity,
                )
            )
        if existing is not None:
            return self._replay_or_conflict(existing, payload_digest, type(model))
        try:
            connection.execute(
                AgentCanvasGuidedProductionReceiptRow.__table__.insert().values(
                    receipt_id=receipt_id,
                    receipt_type=receipt_type,
                    logical_identity=logical_identity,
                    workflow_id=workflow_id,
                    payload_digest=payload_digest,
                    payload_json=payload_json,
                    created_at=created_at,
                )
            )
        except IntegrityError as error:
            raise _error(
                "guided_production_receipt_conflict",
                "Guided production receipt identity was claimed concurrently.",
            ) from error
        return model

    def _get(
        self,
        receipt_type: ReceiptType,
        receipt_id: str,
        model_type: type[ReceiptT],
    ) -> ReceiptT:
        try:
            with self._database.session_factory() as session:
                row = session.scalar(
                    select(AgentCanvasGuidedProductionReceiptRow).where(
                        AgentCanvasGuidedProductionReceiptRow.receipt_type == receipt_type,
                        AgentCanvasGuidedProductionReceiptRow.receipt_id == receipt_id,
                    )
                )
        except SQLAlchemyError as error:
            raise _error(
                "guided_production_receipt_persistence_failed",
                "Guided production receipt storage is unavailable.",
            ) from error
        if row is None:
            raise _error(
                "guided_production_receipt_not_found",
                "Guided production receipt was not found.",
            )
        return model_type.model_validate_json(row.payload_json)

    def _list(self, receipt_type: ReceiptType, workflow_id: str) -> tuple[ReceiptModel, ...]:
        try:
            with self._database.session_factory() as session:
                rows = session.scalars(
                    select(AgentCanvasGuidedProductionReceiptRow)
                    .where(
                        AgentCanvasGuidedProductionReceiptRow.receipt_type == receipt_type,
                        AgentCanvasGuidedProductionReceiptRow.workflow_id == workflow_id,
                    )
                    .order_by(
                        AgentCanvasGuidedProductionReceiptRow.created_at.asc(),
                        AgentCanvasGuidedProductionReceiptRow.receipt_id.asc(),
                    )
                ).all()
        except SQLAlchemyError as error:
            raise _error(
                "guided_production_receipt_persistence_failed",
                "Guided production receipt storage is unavailable.",
            ) from error
        model_type = _MODEL_BY_TYPE[receipt_type]
        return tuple(model_type.model_validate_json(row.payload_json) for row in rows)

    def _get_by_identity(
        self,
        receipt_type: ReceiptType,
        logical_identity: str,
        payload_digest: str,
        model_type: type[ReceiptT],
    ) -> ReceiptT:
        with self._database.session_factory() as session:
            row = session.scalar(
                select(AgentCanvasGuidedProductionReceiptRow).where(
                    AgentCanvasGuidedProductionReceiptRow.receipt_type == receipt_type,
                    AgentCanvasGuidedProductionReceiptRow.logical_identity == logical_identity,
                )
            )
        if row is None:
            raise _error(
                "guided_production_receipt_persistence_failed",
                "Guided production receipt storage is unavailable.",
            )
        return self._replay_or_conflict(row, payload_digest, model_type)

    @staticmethod
    def _replay_or_conflict(
        row: AgentCanvasGuidedProductionReceiptRow,
        payload_digest: str,
        model_type: type[ReceiptT],
    ) -> ReceiptT:
        if row.payload_digest != payload_digest:
            raise _error(
                "guided_production_receipt_conflict",
                "Guided production receipt identity was reused with different evidence.",
            )
        return model_type.model_validate_json(row.payload_json)


def _canonical_payload(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _receipt_id(model: BaseModel) -> str:
    for field in ("confirmation_id", "fanout_plan_id", "receipt_id"):
        value = getattr(model, field, None)
        if value:
            return str(value)
    raise ValueError("Guided production receipt has no identifier.")


def _created_at(model: BaseModel) -> str:
    for field in ("confirmed_at", "committed_at", "completed_at", "created_at"):
        value = getattr(model, field, None)
        if value is not None:
            return value.isoformat()
    raise ValueError("Guided production receipt has no timestamp.")


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_production_closure_repository")
