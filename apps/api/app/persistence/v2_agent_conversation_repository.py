"""Transactional SQLite repository for visible V2 Agent conversations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.models import (
    V2AgentActionRow,
    V2AgentConversationRow,
    V2AgentMessageRow,
)
from app.schemas.v2_agent_conversations import (
    V2AgentAction,
    V2AgentActionCreate,
    V2AgentActionStatus,
    V2AgentConversation,
    V2AgentConversationCreate,
    V2AgentConversationPage,
    V2AgentMessage,
    V2AgentMessageCreate,
    V2AgentMessagePage,
    _validate_safe_json,
)


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_TRANSITIONS = {
    "queued": {"running"},
    "running": _TERMINAL_STATUSES,
}


class V2AgentConversationRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class V2AgentConversationRepository:
    def __init__(self, database: V2Database) -> None:
        self._database = database

    def create_conversation(
        self,
        request: V2AgentConversationCreate,
    ) -> V2AgentConversation:
        timestamp = _now()
        values = {
            "conversation_id": request.conversation_id,
            "workflow_id": request.workflow_id,
            "status": "active",
            "title": request.title,
            "rolling_summary": "",
            "last_message_sequence": 0,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        try:
            with self._database.engine.begin() as connection:
                connection.execute(insert(V2AgentConversationRow).values(**values))
        except IntegrityError:
            existing = self.get_conversation(
                request.workflow_id,
                request.conversation_id,
            )
            if existing.title != request.title:
                raise V2AgentConversationRepositoryError(
                    "agent_conversation_conflict",
                    "Conversation identity already exists with different input.",
                )
            return existing
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return V2AgentConversation.model_validate(values)

    def get_conversation(
        self,
        workflow_id: str,
        conversation_id: str,
    ) -> V2AgentConversation:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(V2AgentConversationRow).where(
                            V2AgentConversationRow.conversation_id == conversation_id,
                            V2AgentConversationRow.workflow_id == workflow_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise V2AgentConversationRepositoryError(
                "agent_conversation_not_found",
                "Agent conversation was not found.",
            )
        return _conversation(row)

    def list_conversations(
        self,
        workflow_id: str,
        *,
        after: str | None = None,
        limit: int = 50,
    ) -> V2AgentConversationPage:
        bounded_limit = max(1, min(limit, 100))
        query = select(V2AgentConversationRow).where(
            V2AgentConversationRow.workflow_id == workflow_id
        )
        if after:
            query = query.where(V2AgentConversationRow.conversation_id > after)
        query = query.order_by(V2AgentConversationRow.conversation_id).limit(bounded_limit + 1)
        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(query).mappings().all()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        has_more = len(rows) > bounded_limit
        items = [_conversation(row) for row in rows[:bounded_limit]]
        return V2AgentConversationPage(
            items=items,
            next_cursor=items[-1].conversation_id if has_more and items else None,
        )

    def append_message(self, request: V2AgentMessageCreate) -> V2AgentMessage:
        timestamp = _now()
        try:
            with self._database.engine.begin() as connection:
                conversation = _conversation_row(connection, request.conversation_id)
                sequence_no = int(conversation["last_message_sequence"]) + 1
                values = {
                    "message_id": request.message_id,
                    "conversation_id": request.conversation_id,
                    "sequence_no": sequence_no,
                    "role": request.role,
                    "content": request.content,
                    "target_json": _json_or_none(request.target),
                    "created_at": timestamp,
                }
                connection.execute(insert(V2AgentMessageRow).values(**values))
                connection.execute(
                    update(V2AgentConversationRow)
                    .where(V2AgentConversationRow.conversation_id == request.conversation_id)
                    .values(
                        last_message_sequence=sequence_no,
                        updated_at=timestamp,
                    )
                )
        except IntegrityError as error:
            existing = self._load_message(request.message_id)
            if (
                existing.conversation_id == request.conversation_id
                and existing.role == request.role
                and existing.content == request.content
                and existing.target == request.target
            ):
                return existing
            raise V2AgentConversationRepositoryError(
                "agent_message_conflict",
                "Message identity already exists with different input.",
            ) from error
        except V2AgentConversationRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return V2AgentMessage(
            message_id=request.message_id,
            conversation_id=request.conversation_id,
            sequence_no=sequence_no,
            role=request.role,
            content=request.content,
            target=request.target,
            created_at=timestamp,
        )

    def list_messages(
        self,
        conversation_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 50,
    ) -> V2AgentMessagePage:
        bounded_limit = max(1, min(limit, 100))
        query = select(V2AgentMessageRow).where(
            V2AgentMessageRow.conversation_id == conversation_id
        )
        if after_sequence is not None:
            query = query.where(V2AgentMessageRow.sequence_no > after_sequence)
        query = query.order_by(V2AgentMessageRow.sequence_no).limit(bounded_limit + 1)
        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(query).mappings().all()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        has_more = len(rows) > bounded_limit
        items = [_message(row) for row in rows[:bounded_limit]]
        return V2AgentMessagePage(
            items=items,
            next_cursor=items[-1].sequence_no if has_more and items else None,
        )

    def create_or_load_action(
        self,
        request: V2AgentActionCreate,
    ) -> tuple[V2AgentAction, bool]:
        timestamp = _now()
        values = {
            "action_id": request.action_id,
            "conversation_id": request.conversation_id,
            "request_id": request.request_id,
            "action_mode": request.action_mode,
            "target_json": _json_or_none(request.target),
            "status": "queued",
            "result_json": None,
            "error_code": None,
            "error_message": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        try:
            with self._database.engine.begin() as connection:
                _conversation_row(connection, request.conversation_id)
                existing = (
                    connection.execute(
                        select(V2AgentActionRow).where(
                            V2AgentActionRow.conversation_id == request.conversation_id,
                            V2AgentActionRow.request_id == request.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    action = _action(existing)
                    if action.action_mode != request.action_mode or action.target != request.target:
                        raise V2AgentConversationRepositoryError(
                            "agent_action_idempotency_conflict",
                            "Action request identity was reused with different input.",
                        )
                    return action, False
                connection.execute(insert(V2AgentActionRow).values(**values))
        except V2AgentConversationRepositoryError:
            raise
        except IntegrityError as error:
            raise V2AgentConversationRepositoryError(
                "agent_action_idempotency_conflict",
                "Action request identity was reused with different input.",
            ) from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return (
            V2AgentAction(
                action_id=request.action_id,
                conversation_id=request.conversation_id,
                request_id=request.request_id,
                action_mode=request.action_mode,
                target=request.target,
                status="queued",
                result=None,
                created_at=timestamp,
                updated_at=timestamp,
            ),
            True,
        )

    def transition_action(
        self,
        action_id: str,
        *,
        status: V2AgentActionStatus,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> V2AgentAction:
        if result is not None:
            _validate_safe_json(result)
        timestamp = _now()
        try:
            with self._database.engine.begin() as connection:
                row = _action_row(connection, action_id)
                current = _action(row)
                if current.status in _TERMINAL_STATUSES:
                    if current.status == status and (
                        current.result == result
                        and current.error_code == error_code
                        and current.error_message == error_message
                    ):
                        return current
                    raise V2AgentConversationRepositoryError(
                        "agent_action_terminal",
                        "Terminal Agent action state is immutable.",
                    )
                if status not in _TRANSITIONS.get(current.status, set()):
                    raise V2AgentConversationRepositoryError(
                        "agent_action_transition_invalid",
                        "Agent action status transition is invalid.",
                    )
                connection.execute(
                    update(V2AgentActionRow)
                    .where(V2AgentActionRow.action_id == action_id)
                    .values(
                        status=status,
                        result_json=_json_or_none(result),
                        error_code=error_code,
                        error_message=error_message,
                        updated_at=timestamp,
                    )
                )
                updated = _action_row(connection, action_id)
        except V2AgentConversationRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _action(updated)

    def list_actions(self, conversation_id: str) -> list[V2AgentAction]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(V2AgentActionRow)
                        .where(V2AgentActionRow.conversation_id == conversation_id)
                        .order_by(
                            V2AgentActionRow.created_at,
                            V2AgentActionRow.action_id,
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return [_action(row) for row in rows]

    def update_summary(
        self,
        conversation_id: str,
        summary: str,
    ) -> V2AgentConversation:
        if len(summary.encode("utf-8")) > 16_384:
            raise ValueError("Conversation summary exceeds the size limit")
        try:
            with self._database.engine.begin() as connection:
                row = _conversation_row(connection, conversation_id)
                connection.execute(
                    update(V2AgentConversationRow)
                    .where(V2AgentConversationRow.conversation_id == conversation_id)
                    .values(rolling_summary=summary, updated_at=_now())
                )
                updated = _conversation_row(connection, conversation_id)
        except V2AgentConversationRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _conversation(updated or row)

    def load_context(
        self,
        conversation_id: str,
        *,
        limit: int,
    ) -> tuple[str, list[dict[str, object]]]:
        try:
            with self._database.engine.connect() as connection:
                conversation = _conversation_row(connection, conversation_id)
                rows = (
                    connection.execute(
                        select(V2AgentMessageRow)
                        .where(V2AgentMessageRow.conversation_id == conversation_id)
                        .order_by(V2AgentMessageRow.sequence_no.desc())
                        .limit(max(1, min(limit, 32)))
                    )
                    .mappings()
                    .all()
                )
        except V2AgentConversationRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return str(conversation["rolling_summary"]), [
            _message(row).model_dump(mode="json") for row in reversed(rows)
        ]

    def _load_message(self, message_id: str) -> V2AgentMessage:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(V2AgentMessageRow).where(V2AgentMessageRow.message_id == message_id)
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise V2AgentConversationRepositoryError(
                "agent_message_not_found",
                "Agent message was not found.",
            )
        return _message(row)


def _conversation_row(connection, conversation_id: str):
    row = (
        connection.execute(
            select(V2AgentConversationRow).where(
                V2AgentConversationRow.conversation_id == conversation_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise V2AgentConversationRepositoryError(
            "agent_conversation_not_found",
            "Agent conversation was not found.",
        )
    return row


def _action_row(connection, action_id: str):
    row = (
        connection.execute(select(V2AgentActionRow).where(V2AgentActionRow.action_id == action_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise V2AgentConversationRepositoryError(
            "agent_action_not_found",
            "Agent action was not found.",
        )
    return row


def _conversation(row) -> V2AgentConversation:
    return V2AgentConversation(
        conversation_id=row["conversation_id"],
        workflow_id=row["workflow_id"],
        status=row["status"],
        title=row["title"],
        rolling_summary=row["rolling_summary"],
        last_message_sequence=row["last_message_sequence"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message(row) -> V2AgentMessage:
    return V2AgentMessage(
        message_id=row["message_id"],
        conversation_id=row["conversation_id"],
        sequence_no=row["sequence_no"],
        role=row["role"],
        content=row["content"],
        target=_load_json(row["target_json"]),
        created_at=row["created_at"],
    )


def _action(row) -> V2AgentAction:
    return V2AgentAction(
        action_id=row["action_id"],
        conversation_id=row["conversation_id"],
        request_id=row["request_id"],
        action_mode=row["action_mode"],
        target=_load_json(row["target_json"]),
        status=row["status"],
        result=_load_json(row["result_json"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _json_or_none(value: Any | None) -> str | None:
    if value is None:
        return None
    _validate_safe_json(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _load_json(value: str | None) -> dict[str, Any] | None:
    parsed = json.loads(value) if value else None
    return parsed if isinstance(parsed, dict) else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persistence_error() -> V2AgentConversationRepositoryError:
    return V2AgentConversationRepositoryError(
        "agent_conversation_persistence_failed",
        "Agent conversation persistence failed.",
    )
