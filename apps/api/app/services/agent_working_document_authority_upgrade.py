"""Fail-closed pre-release upgrade for authoritative Agent working documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from sqlalchemy import select

from app.persistence.database import V2Database
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasNodeRow,
    AgentCanvasRequirementLedgerRow,
    AgentWorkingDocumentRow,
)
from app.persistence.agent_working_document_repository import AgentWorkingDocumentRepository
from app.schemas.agent_working_documents import (
    AgentAnchorV2,
    AgentAnchorV3,
    AgentAnchorNodeSourceV3,
    AnchorAcceptanceEvidenceV1,
    AnchorRegistryContentV2,
    AnchorRegistryContentV3,
)


_NODE_ROLE_TO_ANCHOR_ROLE = {
    "world_setting": "world_setting",
    "world_view": "world_setting",
    "product": "product",
    "product_main": "product",
    "product_multiview": "product",
    "prop": "prop",
    "character": "character",
    "character_main": "character",
    "character_turnaround": "character",
    "scene": "scene",
    "editing": "composition",
}


@dataclass(frozen=True)
class AgentWorkingDocumentAuthorityUpgradeReport:
    upgraded_document_ids: tuple[str, ...]
    ambiguous_document_ids: tuple[str, ...]


class AgentWorkingDocumentAuthorityUpgradeService:
    """Upgrade only legacy rows whose role and source are SQLite-provable."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Working-document upgrade services must share one database.")
        self._database = database
        self._documents = AgentWorkingDocumentRepository(database, events)

    def upgrade(self) -> AgentWorkingDocumentAuthorityUpgradeReport:
        upgraded: list[str] = []
        ambiguous: list[str] = []
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                rows = (
                    connection.execute(
                        select(AgentWorkingDocumentRow).where(
                            AgentWorkingDocumentRow.content_schema_version == 2,
                            AgentWorkingDocumentRow.document_kind == "anchor_registry",
                        )
                    )
                    .mappings()
                    .all()
                )
                for row in rows:
                    document_id = str(row["document_id"])
                    content = AnchorRegistryContentV2.model_validate_json(str(row["content_json"]))
                    upgraded_content = self._upgrade_anchor_content(
                        connection,
                        workflow_id=str(row["workflow_id"]),
                        document_id=document_id,
                        next_revision=int(row["revision"]) + 1,
                        content=content,
                    )
                    if upgraded_content is None:
                        ambiguous.append(document_id)
                        continue
                    request_digest = AgentWorkingDocumentRepository.digest_content(upgraded_content)
                    self._documents.apply_content_in_transaction(
                        connection,
                        document_id=document_id,
                        expected_revision=int(row["revision"]),
                        operation="upgrade_authority_v3",
                        content=upgraded_content,
                        agent_run_id="system:authority-v3-upgrade",
                        idempotency_key="authority-v3-upgrade",
                        now=datetime.now(timezone.utc),
                        request_digest=request_digest,
                    )
                    upgraded.append(document_id)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return AgentWorkingDocumentAuthorityUpgradeReport(
            upgraded_document_ids=tuple(upgraded),
            ambiguous_document_ids=tuple(ambiguous),
        )

    @staticmethod
    def _upgrade_anchor_content(
        connection,
        *,
        workflow_id: str,
        document_id: str,
        next_revision: int,
        content: AnchorRegistryContentV2,
    ) -> AnchorRegistryContentV3 | None:
        ledger = (
            connection.execute(
                select(AgentCanvasRequirementLedgerRow).where(
                    AgentCanvasRequirementLedgerRow.workflow_id == workflow_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if ledger is None:
            return None
        anchors: list[AgentAnchorV3] = []
        for legacy in content.anchors:
            anchor = _upgrade_node_anchor(
                connection,
                workflow_id=workflow_id,
                document_id=document_id,
                next_revision=next_revision,
                requirement_revision_id=str(ledger["current_revision_id"]),
                requirement_revision_no=int(ledger["current_revision_no"]),
                legacy=legacy,
            )
            if anchor is None:
                return None
            anchors.append(anchor)
        return AnchorRegistryContentV3(schema_version="3", anchors=tuple(anchors))


def _upgrade_node_anchor(
    connection,
    *,
    workflow_id: str,
    document_id: str,
    next_revision: int,
    requirement_revision_id: str,
    requirement_revision_no: int,
    legacy: AgentAnchorV2,
) -> AgentAnchorV3 | None:
    if legacy.source_kind != "node" or legacy.source_id is None:
        return None
    node = (
        connection.execute(
            select(AgentCanvasNodeRow).where(
                AgentCanvasNodeRow.workflow_id == workflow_id,
                AgentCanvasNodeRow.node_id == legacy.source_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if node is None:
        return None
    semantic_role = _NODE_ROLE_TO_ANCHOR_ROLE.get(str(node["creative_role"]))
    if semantic_role is None:
        return None
    node_revision = int(node["revision"])
    identity_digest = hashlib.sha256(
        f"{workflow_id}:{document_id}:{legacy.alias}:{legacy.source_id}".encode("utf-8")
    ).hexdigest()[:32]
    return AgentAnchorV3(
        alias=legacy.alias,
        identity_id=f"identity_{identity_digest}",
        semantic_role=semantic_role,
        display_name=legacy.display_name,
        summary=legacy.summary,
        lifecycle="invalid",
        source=AgentAnchorNodeSourceV3(
            workflow_id=workflow_id,
            node_id=legacy.source_id,
            node_revision=node_revision,
        ),
        acceptance_evidence=(
            AnchorAcceptanceEvidenceV1(
                evidence_id=f"migration_{identity_digest}",
                actor="system",
                decision="invalidated",
                action_id="authority-v3-upgrade",
                requirement_revision_id=requirement_revision_id,
                requirement_revision_no=requirement_revision_no,
                node_revision=node_revision,
                document_revision=next_revision,
                recorded_at=datetime.now(timezone.utc),
            ),
        ),
    )
