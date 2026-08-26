"""SQLite authority for typed Agent working documents."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentWorkingDocumentPatchReceiptRow,
    AgentWorkingDocumentRow,
    AgentCanvasChatEntryRow,
    AgentCanvasConversationRow,
    AgentCanvasGuidanceSessionRow,
)
from app.schemas.agent_working_documents import (
    AgentWorkingDocumentContentV2,
    AgentWorkingDocumentKindV2,
    AgentWorkingDocumentPageV2,
    AgentWorkingDocumentV2,
    AnchorRegistryContentV2,
    AnchorRegistryContentV3,
    PERSISTED_STORYBOARD_PLAN_NARRATIVE_MAX_LENGTH,
    StoryboardProductionPlanContentV2,
    StoryboardProductionPlanContentV3,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_user_presentation import build_presentation_metadata


class AgentWorkingDocumentRepository:
    """Persist current documents and idempotent typed patch results."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Working documents and events must use the same database.")
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    @staticmethod
    def validate_document_payload(payload: dict[str, Any]) -> AgentWorkingDocumentV2:
        """Validate one complete document payload before a caller mutates storage."""

        return _document_from_payload(payload)

    @staticmethod
    def validate_document_row(row: RowMapping) -> AgentWorkingDocumentV2:
        """Validate one complete document row before a caller projects it."""

        return _document(row)

    @staticmethod
    def digest_content(content: AgentWorkingDocumentContentV2 | dict[str, Any]) -> str:
        payload = _validated_content_payload(content)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def digest_patch(patch: BaseModel, *, agent_run_id: str) -> str:
        payload = json.dumps(
            {
                "agent_run_id": agent_run_id,
                "patch": patch.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    def get_patch_replay(
        self,
        *,
        document_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> AgentWorkingDocumentV2 | None:
        try:
            with self._database.engine.connect() as connection:
                receipt = (
                    connection.execute(
                        select(AgentWorkingDocumentPatchReceiptRow).where(
                            AgentWorkingDocumentPatchReceiptRow.document_id == document_id,
                            AgentWorkingDocumentPatchReceiptRow.idempotency_key == idempotency_key,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        if receipt is None:
            return None
        if str(receipt["request_digest"]) != request_digest:
            raise _error(
                "agent_document_idempotency_conflict",
                "The patch key was already used for another request.",
            )
        return _document_from_json(str(receipt["result_json"]))

    def create(
        self,
        *,
        workflow_id: str,
        guidance_session_id: str,
        kind: AgentWorkingDocumentKindV2,
        title: str,
        content: AgentWorkingDocumentContentV2 | dict[str, Any],
        agent_run_id: str,
        now: datetime,
        document_id: str | None = None,
    ) -> AgentWorkingDocumentV2:
        document_id = document_id or f"adoc_{uuid4().hex}"
        typed_content = _typed_content(kind, content)
        digest = self.digest_content(typed_content)
        document = AgentWorkingDocumentV2(
            document_id=document_id,
            workflow_id=workflow_id,
            guidance_session_id=guidance_session_id,
            kind=kind,
            title=title,
            revision=1,
            content_schema_version=_content_schema_version(typed_content),
            content_digest=digest,
            content=typed_content,
            created_by_agent_run_id=agent_run_id,
            updated_by_agent_run_id=agent_run_id,
            created_at=now,
            updated_at=now,
        )
        try:
            with self._database.engine.begin() as connection:
                connection.execute(
                    insert(AgentWorkingDocumentRow).values(**_document_values(document))
                )
                self._events.append_in_transaction(
                    connection,
                    _document_event(document, event_type="agent_document_created"),
                )
                _append_timeline_reference(connection, document)
        except IntegrityError as error:
            if self.get_by_kind(workflow_id, guidance_session_id, kind) is not None:
                raise _error(
                    "agent_document_kind_conflict",
                    "A working document already exists for this session and kind.",
                ) from error
            raise _error(
                "agent_document_patch_invalid",
                "Working document references are invalid.",
            ) from error
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return document

    def create_in_transaction(
        self,
        connection: Connection,
        *,
        workflow_id: str,
        guidance_session_id: str,
        kind: AgentWorkingDocumentKindV2,
        title: str,
        content: AgentWorkingDocumentContentV2 | dict[str, Any],
        agent_run_id: str,
        idempotency_key: str,
        request_digest: str,
        now: datetime,
        document_id: str,
    ) -> AgentWorkingDocumentV2:
        """Create one document and its replay receipt in an owning transaction."""

        receipt = (
            connection.execute(
                select(AgentWorkingDocumentPatchReceiptRow).where(
                    AgentWorkingDocumentPatchReceiptRow.document_id == document_id,
                    AgentWorkingDocumentPatchReceiptRow.idempotency_key == idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if receipt is not None:
            if str(receipt["request_digest"]) != request_digest:
                raise _error(
                    "agent_document_idempotency_conflict",
                    "The patch key was already used for another request.",
                )
            return _document_from_json(str(receipt["result_json"]))
        existing = connection.execute(
            select(AgentWorkingDocumentRow.document_id).where(
                AgentWorkingDocumentRow.workflow_id == workflow_id,
                AgentWorkingDocumentRow.guidance_session_id == guidance_session_id,
                AgentWorkingDocumentRow.document_kind == kind,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise _error(
                "agent_document_kind_conflict",
                "A working document already exists for this session and kind.",
            )

        typed_content = _typed_content(kind, content)
        document = AgentWorkingDocumentV2(
            document_id=document_id,
            workflow_id=workflow_id,
            guidance_session_id=guidance_session_id,
            kind=kind,
            title=title,
            revision=1,
            content_schema_version=_content_schema_version(typed_content),
            content_digest=self.digest_content(typed_content),
            content=typed_content,
            created_by_agent_run_id=agent_run_id,
            updated_by_agent_run_id=agent_run_id,
            created_at=now,
            updated_at=now,
        )
        connection.execute(insert(AgentWorkingDocumentRow).values(**_document_values(document)))
        connection.execute(
            insert(AgentWorkingDocumentPatchReceiptRow).values(
                receipt_id=f"adoc_patch_{uuid4().hex}",
                document_id=document_id,
                idempotency_key=idempotency_key,
                operation="create_guided_document",
                request_digest=request_digest,
                before_revision=0,
                after_revision=1,
                result_digest=document.content_digest,
                result_json=document.model_dump_json(),
                created_at=_iso(now),
            )
        )
        self._events.append_in_transaction(
            connection,
            _document_event(document, event_type="agent_document_created"),
        )
        self._events.append_in_transaction(
            connection,
            _document_event(
                document,
                event_type="agent_document_revision_created",
                transition_key=f"agent-document-revision:{document_id}:1",
            ),
        )
        _append_timeline_reference(connection, document)
        return document

    def get(self, document_id: str) -> AgentWorkingDocumentV2 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentWorkingDocumentRow).where(
                            AgentWorkingDocumentRow.document_id == document_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return _document(row) if row is not None else None

    def get_by_kind(
        self,
        workflow_id: str,
        guidance_session_id: str,
        kind: AgentWorkingDocumentKindV2,
    ) -> AgentWorkingDocumentV2 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentWorkingDocumentRow).where(
                            AgentWorkingDocumentRow.workflow_id == workflow_id,
                            AgentWorkingDocumentRow.guidance_session_id == guidance_session_id,
                            AgentWorkingDocumentRow.document_kind == kind,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        return _document(row) if row is not None else None

    def list(
        self,
        workflow_id: str,
        *,
        kind: AgentWorkingDocumentKindV2 | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> AgentWorkingDocumentPageV2:
        if not 1 <= limit <= 100:
            raise _pagination_error()
        cursor_values = _decode_cursor(cursor) if cursor is not None else None
        conditions = [AgentWorkingDocumentRow.workflow_id == workflow_id]
        if kind is not None:
            conditions.append(AgentWorkingDocumentRow.document_kind == kind)
        if cursor_values is not None:
            updated_at, document_id = cursor_values
            conditions.append(
                or_(
                    AgentWorkingDocumentRow.updated_at < updated_at,
                    and_(
                        AgentWorkingDocumentRow.updated_at == updated_at,
                        AgentWorkingDocumentRow.document_id > document_id,
                    ),
                )
            )
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentWorkingDocumentRow)
                        .where(*conditions)
                        .order_by(
                            AgentWorkingDocumentRow.updated_at.desc(),
                            AgentWorkingDocumentRow.document_id.asc(),
                        )
                        .limit(limit + 1)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _unavailable_error() from error
        page_rows = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page_rows:
            last = page_rows[-1]
            next_cursor = _encode_cursor(str(last["updated_at"]), str(last["document_id"]))
        return AgentWorkingDocumentPageV2(
            items=tuple(_document(row) for row in page_rows),
            next_cursor=next_cursor,
        )

    def apply_patch(
        self,
        *,
        document_id: str,
        expected_revision: int,
        operation: str,
        content: AgentWorkingDocumentContentV2 | dict[str, Any],
        agent_run_id: str,
        idempotency_key: str,
        now: datetime,
        request_digest: str | None = None,
    ) -> AgentWorkingDocumentV2:
        request_digest = request_digest or _request_digest(
            document_id=document_id,
            expected_revision=expected_revision,
            operation=operation,
            content=content,
            agent_run_id=agent_run_id,
        )
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    next_document = self.apply_content_in_transaction(
                        connection,
                        document_id=document_id,
                        expected_revision=expected_revision,
                        operation=operation,
                        content=content,
                        agent_run_id=agent_run_id,
                        idempotency_key=idempotency_key,
                        now=now,
                        request_digest=request_digest,
                    )
                    connection.commit()
                    return next_document
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _unavailable_error() from error

    @staticmethod
    def digest_mutation(
        *,
        document_id: str,
        expected_revision: int,
        operation: str,
        content: AgentWorkingDocumentContentV2 | dict[str, Any],
        agent_run_id: str,
    ) -> str:
        """Return the canonical identity for a planned document mutation."""

        return _request_digest(
            document_id=document_id,
            expected_revision=expected_revision,
            operation=operation,
            content=content,
            agent_run_id=agent_run_id,
        )

    def apply_content_in_transaction(
        self,
        connection: Connection,
        *,
        document_id: str,
        expected_revision: int,
        operation: str,
        content: AgentWorkingDocumentContentV2 | dict[str, Any],
        agent_run_id: str,
        idempotency_key: str,
        now: datetime,
        request_digest: str,
    ) -> AgentWorkingDocumentV2:
        """Apply one replay-safe CAS mutation inside an owning transaction."""

        receipt = (
            connection.execute(
                select(AgentWorkingDocumentPatchReceiptRow).where(
                    AgentWorkingDocumentPatchReceiptRow.document_id == document_id,
                    AgentWorkingDocumentPatchReceiptRow.idempotency_key == idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if receipt is not None:
            if str(receipt["request_digest"]) != request_digest:
                raise _error(
                    "agent_document_idempotency_conflict",
                    "The patch key was already used for another request.",
                )
            return _document_from_json(str(receipt["result_json"]))

        current_row = (
            connection.execute(
                select(AgentWorkingDocumentRow).where(
                    AgentWorkingDocumentRow.document_id == document_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if current_row is None:
            raise _error("agent_document_not_found", "Agent working document was not found.")
        current = _document(current_row)
        if current.revision != expected_revision:
            raise V2PersistenceError(
                "agent_document_revision_conflict",
                "Agent working document changed before this patch.",
                stage="agent_working_documents",
                details={"current_revision": current.revision},
            )
        typed_content = _typed_content(current.kind, content)
        next_document = current.model_copy(
            update={
                "revision": current.revision + 1,
                "content_schema_version": _content_schema_version(typed_content),
                "content": typed_content,
                "content_digest": self.digest_content(typed_content),
                "updated_by_agent_run_id": agent_run_id,
                "updated_at": now,
            }
        )
        result = connection.execute(
            update(AgentWorkingDocumentRow)
            .where(
                AgentWorkingDocumentRow.document_id == document_id,
                AgentWorkingDocumentRow.revision == expected_revision,
            )
            .values(
                revision=next_document.revision,
                content_schema_version=next_document.content_schema_version,
                content_digest=next_document.content_digest,
                content_json=_content_json(next_document.content),
                updated_by_agent_run_id=agent_run_id,
                updated_at=_iso(now),
            )
        )
        if result.rowcount != 1:
            raise _error(
                "agent_document_revision_conflict",
                "Agent working document changed before this patch.",
            )
        connection.execute(
            insert(AgentWorkingDocumentPatchReceiptRow).values(
                receipt_id=f"adoc_patch_{uuid4().hex}",
                document_id=document_id,
                idempotency_key=idempotency_key,
                operation=operation,
                request_digest=request_digest,
                before_revision=current.revision,
                after_revision=next_document.revision,
                result_digest=next_document.content_digest,
                result_json=next_document.model_dump_json(),
                created_at=_iso(now),
            )
        )
        self._events.append_in_transaction(
            connection,
            _document_event(
                next_document,
                event_type="agent_document_updated",
                transition_key=f"agent-document:{document_id}:{next_document.revision}",
            ),
        )
        self._events.append_in_transaction(
            connection,
            _document_event(
                next_document,
                event_type="agent_document_revision_created",
                transition_key=(f"agent-document-revision:{document_id}:{next_document.revision}"),
            ),
        )
        if operation == "upsert_anchor":
            self._events.append_in_transaction(
                connection,
                _document_event(
                    next_document,
                    event_type="anchor_registered",
                    transition_key=f"anchor-registered:{document_id}:{next_document.revision}",
                ),
            )
        _append_timeline_reference(connection, next_document)
        return next_document


def _typed_content(
    kind: AgentWorkingDocumentKindV2,
    content: AgentWorkingDocumentContentV2 | dict[str, Any],
) -> AgentWorkingDocumentContentV2:
    payload = _content_payload(content)
    is_v3 = isinstance(payload, dict) and payload.get("schema_version") == "3"
    model = (
        (AnchorRegistryContentV3 if is_v3 else AnchorRegistryContentV2)
        if kind == "anchor_registry"
        else (StoryboardProductionPlanContentV3 if is_v3 else StoryboardProductionPlanContentV2)
    )
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise _content_invalid_error(kind, payload) from error


def _content_schema_version(content: AgentWorkingDocumentContentV2) -> int:
    return 3 if getattr(content, "schema_version", None) == "3" else 2


def _content_payload(content: AgentWorkingDocumentContentV2 | dict[str, Any]) -> Any:
    if isinstance(content, BaseModel):
        return content.model_dump(mode="json")
    return content


def _validated_content_payload(
    content: AgentWorkingDocumentContentV2 | dict[str, Any],
) -> Any:
    payload = _content_payload(content)
    if isinstance(content, (AnchorRegistryContentV2, AnchorRegistryContentV3)) or (
        isinstance(payload, dict) and "anchors" in payload
    ):
        return _content_payload(_typed_content("anchor_registry", payload))
    if isinstance(
        content,
        (StoryboardProductionPlanContentV2, StoryboardProductionPlanContentV3),
    ) or (isinstance(payload, dict) and "narrative_outline" in payload):
        return _content_payload(_typed_content("storyboard_production_plan", payload))
    return payload


def _content_json(content: AgentWorkingDocumentContentV2) -> str:
    return json.dumps(
        _content_payload(content),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _document_values(document: AgentWorkingDocumentV2) -> dict[str, object]:
    return {
        "document_id": document.document_id,
        "workflow_id": document.workflow_id,
        "guidance_session_id": document.guidance_session_id,
        "document_kind": document.kind,
        "title": document.title,
        "revision": document.revision,
        "content_schema_version": document.content_schema_version,
        "content_digest": document.content_digest,
        "content_json": _content_json(document.content),
        "created_by_agent_run_id": document.created_by_agent_run_id,
        "updated_by_agent_run_id": document.updated_by_agent_run_id,
        "created_at": _iso(document.created_at),
        "updated_at": _iso(document.updated_at),
    }


def _document(row: RowMapping) -> AgentWorkingDocumentV2:
    return _document_from_payload(
        {
            "document_id": row["document_id"],
            "workflow_id": row["workflow_id"],
            "guidance_session_id": row["guidance_session_id"],
            "kind": row["document_kind"],
            "title": row["title"],
            "revision": row["revision"],
            "content_schema_version": row["content_schema_version"],
            "content_digest": row["content_digest"],
            "content": json.loads(str(row["content_json"])),
            "created_by_agent_run_id": row["created_by_agent_run_id"],
            "updated_by_agent_run_id": row["updated_by_agent_run_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def _document_from_json(value: str) -> AgentWorkingDocumentV2:
    try:
        return _document_from_payload(json.loads(value))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise _error(
            "agent_working_document_content_invalid",
            "Agent working document content is invalid.",
        ) from error


def _document_from_payload(payload: dict[str, Any]) -> AgentWorkingDocumentV2:
    kind = str(payload.get("kind", "unknown"))
    content_payload = payload.get("content")
    try:
        typed_content = _typed_content(kind, content_payload)
        return AgentWorkingDocumentV2.model_validate({**payload, "content": typed_content})
    except V2PersistenceError:
        raise
    except ValidationError as error:
        raise _content_invalid_error(kind, content_payload) from error


def _document_event(
    document: AgentWorkingDocumentV2,
    *,
    event_type: str,
    transition_key: str | None = None,
) -> V2EventInsert:
    return V2EventInsert(
        workflow_id=document.workflow_id,
        event_type=event_type,
        transition_key=(
            transition_key or f"agent-document:{document.document_id}:{document.revision}"
        ),
        created_at=_iso(document.updated_at),
        payload={
            "document_id": document.document_id,
            "document_kind": document.kind,
            "revision": document.revision,
            "content_digest": document.content_digest,
            "agent_run_id": document.updated_by_agent_run_id,
        },
    )


def _append_timeline_reference(
    connection: Connection,
    document: AgentWorkingDocumentV2,
) -> None:
    conversation_id = connection.execute(
        select(AgentCanvasConversationRow.conversation_id).where(
            AgentCanvasConversationRow.workflow_id == document.workflow_id
        )
    ).scalar_one_or_none()
    if conversation_id is None:
        return
    sequence_no = (
        int(
            connection.execute(
                select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                    AgentCanvasChatEntryRow.conversation_id == conversation_id
                )
            ).scalar_one()
        )
        + 1
    )
    response_locale = connection.execute(
        select(AgentCanvasGuidanceSessionRow.response_locale).where(
            AgentCanvasGuidanceSessionRow.session_id == document.guidance_session_id
        )
    ).scalar_one_or_none()
    metadata = build_presentation_metadata(
        message_key=None,
        message_args={},
        response_locale=str(response_locale or "und"),
        presentation_key=f"document:{document.document_id}",
        base={
            "type": "agent_document_reference",
            "document_id": document.document_id,
            "document_kind": document.kind,
            "revision": document.revision,
            "content_digest": document.content_digest,
            "title": document.title,
        },
    )
    connection.execute(
        insert(AgentCanvasChatEntryRow).values(
            entry_id=f"entry_{uuid4().hex}",
            conversation_id=str(conversation_id),
            workflow_id=document.workflow_id,
            sequence_no=sequence_no,
            entry_type="agent_document_reference",
            speaker=None,
            content=document.title,
            metadata_json=json.dumps(
                metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            created_at=_iso(document.updated_at),
        )
    )


def _request_digest(
    *,
    document_id: str,
    expected_revision: int,
    operation: str,
    content: AgentWorkingDocumentContentV2 | dict[str, Any],
    agent_run_id: str,
) -> str:
    payload = json.dumps(
        {
            "agent_run_id": agent_run_id,
            "content": _validated_content_payload(content),
            "document_id": document_id,
            "expected_revision": expected_revision,
            "operation": operation,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _encode_cursor(updated_at: str, document_id: str) -> str:
    encoded = json.dumps([updated_at, document_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            not isinstance(values, list)
            or len(values) != 2
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError
        return cast(tuple[str, str], tuple(values))
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise _pagination_error() from error


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Working document timestamps must include a timezone.")
    return value.astimezone(timezone.utc).isoformat()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_working_documents")


def _content_invalid_error(
    kind: str,
    payload: Any,
) -> V2PersistenceError:
    details: dict[str, Any] = {"document_kind": kind}
    if isinstance(payload, dict):
        narrative = payload.get("narrative_outline")
        if isinstance(narrative, str):
            details["narrative_length"] = len(narrative)
            if kind == "storyboard_production_plan":
                details["narrative_budget"] = PERSISTED_STORYBOARD_PLAN_NARRATIVE_MAX_LENGTH
    return V2PersistenceError(
        "agent_working_document_content_invalid",
        "Agent working document content is invalid.",
        stage="agent_working_documents",
        details=details,
    )


def _pagination_error() -> V2PersistenceError:
    return _error("pagination_invalid", "Agent document pagination is invalid.")


def _unavailable_error() -> V2PersistenceError:
    return _error(
        "agent_document_unavailable",
        "Agent working document storage is unavailable.",
    )
