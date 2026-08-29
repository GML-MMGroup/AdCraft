"""Durable bounded SQLite delivery storage for presentation streams."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import PresentationStreamChunkRow, PresentationStreamRow
from app.schemas.agent_canvas_presentation import (
    PresentationStreamEventV1,
    PresentationStreamMetadataV1,
    SafePresentationDeltaV1,
)

MAX_PRESENTATION_CHUNKS = 512
MAX_PRESENTATION_BYTES = 1_048_576
MAX_PRESENTATION_CHUNK_BYTES = 4_096
PRESENTATION_COALESCE_WINDOW = timedelta(milliseconds=100)
PRESENTATION_TERMINAL_RETENTION = timedelta(hours=24)


class PresentationCursorExpiredError(V2PersistenceError):
    """Raised when a replay cursor is older than retained delivery rows."""


class PresentationStreamRepository:
    """Own presentation delivery rows without owning any domain state."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    @property
    def database(self) -> V2Database:
        return self._database

    def create(
        self,
        metadata: PresentationStreamMetadataV1,
        *,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> PresentationStreamMetadataV1:
        """Create one stream or replay its existing idempotent identity."""

        timestamp = _utc(now or datetime.now(timezone.utc))
        values = _metadata_values(metadata, idempotency_key=idempotency_key, now=timestamp)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                existing = (
                    connection.execute(
                        select(PresentationStreamRow).where(
                            PresentationStreamRow.idempotency_key == idempotency_key
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    persisted = _metadata(existing)
                    if persisted.stream_id != metadata.stream_id or (
                        persisted.workflow_id,
                        persisted.generation_id,
                        persisted.stream_kind,
                    ) != (
                        metadata.workflow_id,
                        metadata.generation_id,
                        metadata.stream_kind,
                    ):
                        raise _error(
                            "presentation_stream_identity_conflict",
                            "Presentation stream idempotency identity conflicts.",
                        )
                    connection.commit()
                    return persisted
                connection.execute(insert(PresentationStreamRow).values(**values))
                connection.commit()
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            raise _error(
                "presentation_stream_unavailable",
                "Presentation stream storage is unavailable.",
            ) from exc
        return metadata

    def get(self, workflow_id: str, stream_id: str) -> PresentationStreamMetadataV1:
        """Load a stream only when it belongs to the requested workflow."""

        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(PresentationStreamRow).where(
                            PresentationStreamRow.workflow_id == workflow_id,
                            PresentationStreamRow.stream_id == stream_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as exc:
            raise _error(
                "presentation_stream_unavailable", "Presentation stream storage failed."
            ) from exc
        if row is None:
            raise _error(
                "presentation_stream_not_found",
                "Presentation stream was not found.",
            )
        return _metadata(row)

    def append_event(
        self,
        event: PresentationStreamEventV1,
        *,
        event_key: str,
        now: datetime | None = None,
    ) -> PresentationStreamEventV1:
        """Append one ordered event idempotently for the owning generation."""

        timestamp = _utc(now or datetime.now(timezone.utc))
        event_json = event.model_dump_json()
        return self._append(
            event,
            event_key=event_key,
            event_json=event_json,
            byte_size=len((event.delta or "").encode("utf-8")),
            timestamp=timestamp,
        )

    def append_chunk(
        self,
        delta: SafePresentationDeltaV1,
        *,
        now: datetime | None = None,
    ) -> PresentationStreamEventV1:
        """Append or coalesce a safe delta while enforcing hard bounds."""

        timestamp = _utc(now or datetime.now(timezone.utc))
        if len(delta.text.encode("utf-8")) > MAX_PRESENTATION_CHUNK_BYTES:
            raise _error(
                "presentation_stream_backpressure_exceeded",
                "Presentation chunk exceeds the UTF-8 byte limit.",
            )
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                stream = _stream_for_delta(connection, delta)
                _ensure_open_generation(stream, delta.generation_id)
                last = (
                    connection.execute(
                        select(PresentationStreamChunkRow)
                        .where(PresentationStreamChunkRow.stream_id == delta.stream_id)
                        .order_by(PresentationStreamChunkRow.sequence_no.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if last is not None:
                    previous = PresentationStreamEventV1.model_validate_json(last["event_json"])
                    age = timestamp - _parse_time(last["created_at"])
                    combined = f"{previous.delta or ''}{delta.text}"
                    if (
                        previous.event_type == "delta"
                        and previous.generation_id == delta.generation_id
                        and age <= PRESENTATION_COALESCE_WINDOW
                        and len(combined.encode("utf-8")) <= MAX_PRESENTATION_CHUNK_BYTES
                    ):
                        merged = previous.model_copy(update={"delta": combined})
                        connection.execute(
                            update(PresentationStreamChunkRow)
                            .where(PresentationStreamChunkRow.chunk_id == last["chunk_id"])
                            .values(
                                event_json=merged.model_dump_json(),
                                byte_size=len(combined.encode("utf-8")),
                                created_at=timestamp.isoformat(),
                            )
                        )
                        connection.commit()
                        return merged
                count, total = _chunk_limits(connection, delta.stream_id)
                if (
                    count >= MAX_PRESENTATION_CHUNKS
                    or total + len(delta.text.encode("utf-8")) > MAX_PRESENTATION_BYTES
                ):
                    raise _error(
                        "presentation_stream_backpressure_exceeded",
                        "Presentation stream retention limits were reached.",
                    )
                sequence_no = int(stream["last_sequence_no"]) + 1
                event = PresentationStreamEventV1(
                    stream_id=delta.stream_id,
                    workflow_id=delta.workflow_id,
                    stream_kind=delta.stream_kind,
                    event_type="delta",
                    sequence_no=sequence_no,
                    generation_id=delta.generation_id,
                    turn_id=delta.turn_id,
                    node_id=delta.node_id,
                    node_revision=delta.node_revision,
                    response_locale=delta.response_locale,
                    delta=delta.text,
                )
                connection.execute(
                    insert(PresentationStreamChunkRow).values(
                        stream_id=delta.stream_id,
                        sequence_no=sequence_no,
                        event_key=f"delta:{sequence_no}",
                        event_json=event.model_dump_json(),
                        byte_size=len(delta.text.encode("utf-8")),
                        created_at=timestamp.isoformat(),
                    )
                )
                connection.execute(
                    update(PresentationStreamRow)
                    .where(PresentationStreamRow.stream_id == delta.stream_id)
                    .values(last_sequence_no=sequence_no, updated_at=timestamp.isoformat())
                )
                connection.commit()
                return event
        except V2PersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _error(
                "presentation_stream_unavailable", "Presentation stream storage failed."
            ) from exc

    def finish(
        self,
        stream_id: str,
        *,
        generation_id: str,
        authoritative_id: str,
        content_digest: str,
        event_key: str = "terminal:completed",
        now: datetime | None = None,
    ) -> PresentationStreamEventV1:
        """Publish one idempotent authoritative commit event."""

        return self._terminal(
            stream_id,
            generation_id=generation_id,
            status="completed",
            authoritative_id=authoritative_id,
            content_digest=content_digest,
            event_type="committed",
            event_key=event_key,
            now=now,
        )

    def fail(
        self,
        stream_id: str,
        *,
        generation_id: str,
        error_code: str,
        now: datetime | None = None,
    ) -> PresentationStreamEventV1:
        """Publish one idempotent delivery failure without changing domain state."""

        return self._terminal(
            stream_id,
            generation_id=generation_id,
            status="failed",
            error_code=error_code,
            event_type="failed",
            event_key="terminal:failed",
            now=now,
        )

    def supersede(
        self,
        stream_id: str,
        *,
        generation_id: str,
        now: datetime | None = None,
    ) -> PresentationStreamEventV1:
        """Close an old generation without replacing its authoritative resource."""

        return self._terminal(
            stream_id,
            generation_id=generation_id,
            status="superseded",
            event_type="superseded",
            event_key="terminal:superseded",
            now=now,
        )

    def list_after(
        self,
        workflow_id: str,
        stream_id: str,
        *,
        after_seq: int = 0,
    ) -> tuple[PresentationStreamEventV1, ...]:
        """Replay retained events in stream-local sequence order."""

        metadata = self.get(workflow_id, stream_id)
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(PresentationStreamChunkRow)
                        .where(
                            PresentationStreamChunkRow.stream_id == stream_id,
                            PresentationStreamChunkRow.sequence_no > after_seq,
                        )
                        .order_by(PresentationStreamChunkRow.sequence_no)
                    )
                    .mappings()
                    .all()
                )
                oldest = connection.execute(
                    select(PresentationStreamChunkRow.sequence_no)
                    .where(PresentationStreamChunkRow.stream_id == stream_id)
                    .order_by(PresentationStreamChunkRow.sequence_no)
                    .limit(1)
                ).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise _error(
                "presentation_stream_unavailable", "Presentation stream storage failed."
            ) from exc
        if oldest is not None and after_seq < int(oldest) - 1:
            raise PresentationCursorExpiredError(
                "presentation_stream_cursor_expired",
                "Presentation stream cursor is outside the retained window.",
            )
        del metadata
        return tuple(
            PresentationStreamEventV1.model_validate_json(row["event_json"]) for row in rows
        )

    def cleanup(self, *, now: datetime | None = None) -> int:
        """Remove only terminal delivery rows beyond the retention window."""

        cutoff = _utc(now or datetime.now(timezone.utc)) - PRESENTATION_TERMINAL_RETENTION
        try:
            with self._database.engine.begin() as connection:
                result = connection.execute(
                    delete(PresentationStreamRow).where(
                        PresentationStreamRow.terminal_at.is_not(None),
                        PresentationStreamRow.terminal_at < cutoff.isoformat(),
                    )
                )
        except SQLAlchemyError as exc:
            raise _error(
                "presentation_stream_unavailable", "Presentation stream cleanup failed."
            ) from exc
        return int(result.rowcount or 0)

    def record_timing(
        self,
        stream_id: str,
        phase: str,
        elapsed_ms: int,
        *,
        now: datetime | None = None,
    ) -> None:
        """Record one bounded phase duration without content or transport metadata."""

        if (
            phase
            not in {
                "accepted",
                "queued",
                "context_ready",
                "model_started",
                "first_presentation_byte",
                "model_finished",
                "structured_validated",
                "prompt_compiled",
                "authoritative_persisted",
                "media_scheduled",
            }
            or elapsed_ms < 0
            or elapsed_ms > 900_000
        ):
            raise _error("presentation_timing_invalid", "Presentation timing is invalid.")
        timestamp = _utc(now or datetime.now(timezone.utc)).isoformat()
        try:
            with self._database.engine.begin() as connection:
                row = connection.execute(
                    select(PresentationStreamRow.timing_json).where(
                        PresentationStreamRow.stream_id == stream_id
                    )
                ).scalar_one_or_none()
                if row is None:
                    raise _error(
                        "presentation_stream_not_found", "Presentation stream was not found."
                    )
                timing = json.loads(str(row))
                timing[phase] = elapsed_ms
                connection.execute(
                    update(PresentationStreamRow)
                    .where(PresentationStreamRow.stream_id == stream_id)
                    .values(timing_json=json.dumps(timing, sort_keys=True), updated_at=timestamp)
                )
        except V2PersistenceError:
            raise
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            raise _error(
                "presentation_stream_unavailable", "Presentation timing storage failed."
            ) from exc

    def recover(self, *, now: datetime | None = None) -> int:
        """Run the idempotent delivery cleanup used after a worker restart."""

        return self.cleanup(now=now)

    def _append(
        self,
        event: PresentationStreamEventV1,
        *,
        event_key: str,
        event_json: str,
        byte_size: int,
        timestamp: datetime,
    ) -> PresentationStreamEventV1:
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                stream = _stream_for_event(connection, event)
                existing = (
                    connection.execute(
                        select(PresentationStreamChunkRow).where(
                            PresentationStreamChunkRow.stream_id == event.stream_id,
                            PresentationStreamChunkRow.event_key == event_key,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    connection.commit()
                    return PresentationStreamEventV1.model_validate_json(existing["event_json"])
                _ensure_open_generation(stream, event.generation_id)
                count, total = _chunk_limits(connection, event.stream_id)
                if count >= MAX_PRESENTATION_CHUNKS or total + byte_size > MAX_PRESENTATION_BYTES:
                    raise _error(
                        "presentation_stream_backpressure_exceeded",
                        "Presentation stream retention limits were reached.",
                    )
                sequence_no = int(stream["last_sequence_no"]) + 1
                if sequence_no != event.sequence_no:
                    event = event.model_copy(update={"sequence_no": sequence_no})
                    event_json = event.model_dump_json()
                connection.execute(
                    insert(PresentationStreamChunkRow).values(
                        stream_id=event.stream_id,
                        sequence_no=sequence_no,
                        event_key=event_key,
                        event_json=event_json,
                        byte_size=byte_size,
                        created_at=timestamp.isoformat(),
                    )
                )
                values = {"last_sequence_no": sequence_no, "updated_at": timestamp.isoformat()}
                if event.event_type in {"committed", "failed", "superseded"}:
                    values.update(
                        status={
                            "committed": "completed",
                            "failed": "failed",
                            "superseded": "superseded",
                        }[event.event_type],
                        authoritative_id=event.authoritative_id,
                        content_digest=event.content_digest,
                        error_code=event.error_code,
                        terminal_at=timestamp.isoformat(),
                    )
                connection.execute(
                    update(PresentationStreamRow)
                    .where(PresentationStreamRow.stream_id == event.stream_id)
                    .values(**values)
                )
                connection.commit()
                return event
        except V2PersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _error(
                "presentation_stream_unavailable", "Presentation stream storage failed."
            ) from exc

    def _terminal(
        self,
        stream_id: str,
        *,
        generation_id: str,
        status: str,
        event_type: str,
        event_key: str,
        now: datetime | None = None,
        authoritative_id: str | None = None,
        content_digest: str | None = None,
        error_code: str | None = None,
    ) -> PresentationStreamEventV1:
        stream = self._load_stream(stream_id)
        if stream.status == status:
            events = self.list_after(
                stream.workflow_id, stream_id, after_seq=max(0, stream.last_sequence_no - 1)
            )
            if events:
                return events[-1]
        event = PresentationStreamEventV1(
            stream_id=stream_id,
            workflow_id=stream.workflow_id,
            stream_kind=stream.stream_kind,
            event_type=event_type,  # type: ignore[arg-type]
            sequence_no=stream.last_sequence_no + 1,
            generation_id=generation_id,
            turn_id=stream.turn_id,
            node_id=stream.node_id,
            node_revision=stream.node_revision,
            authoritative_id=authoritative_id,
            content_digest=content_digest,
            error_code=error_code,
        )
        return self.append_event(event, event_key=event_key, now=now)

    def _load_stream(self, stream_id: str) -> PresentationStreamMetadataV1:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(PresentationStreamRow).where(
                            PresentationStreamRow.stream_id == stream_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as exc:
            raise _error(
                "presentation_stream_unavailable", "Presentation stream storage failed."
            ) from exc
        if row is None:
            raise _error("presentation_stream_not_found", "Presentation stream was not found.")
        return _metadata(row)


def _metadata_values(
    metadata: PresentationStreamMetadataV1, *, idempotency_key: str, now: datetime
) -> dict[str, object]:
    return {
        **{key: value for key, value in metadata.model_dump().items() if key != "schema_version"},
        "idempotency_key": idempotency_key,
        "timing_json": "{}",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "terminal_at": now.isoformat() if metadata.status != "open" else None,
    }


def _metadata(row: dict[str, object]) -> PresentationStreamMetadataV1:
    return PresentationStreamMetadataV1.model_validate(
        {
            "schema_version": 1,
            "stream_id": row["stream_id"],
            "workflow_id": row["workflow_id"],
            "stream_kind": row["stream_kind"],
            "generation_id": row["generation_id"],
            "turn_id": row.get("turn_id"),
            "node_id": row.get("node_id"),
            "node_revision": row.get("node_revision"),
            "status": row["status"],
            "last_sequence_no": row["last_sequence_no"],
            "authoritative_id": row.get("authoritative_id"),
            "content_digest": row.get("content_digest"),
            "error_code": row.get("error_code"),
        }
    )


def _stream_for_event(connection: object, event: PresentationStreamEventV1) -> dict[str, object]:
    row = (
        connection.execute(  # type: ignore[union-attr]
            select(PresentationStreamRow).where(PresentationStreamRow.stream_id == event.stream_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["workflow_id"] != event.workflow_id:
        raise _error("presentation_stream_not_found", "Presentation stream was not found.")
    return row


def _stream_for_delta(connection: object, delta: SafePresentationDeltaV1) -> dict[str, object]:
    return _stream_for_event(
        connection,
        PresentationStreamEventV1(
            stream_id=delta.stream_id,
            workflow_id=delta.workflow_id,
            stream_kind=delta.stream_kind,
            event_type="delta",
            sequence_no=1,
            generation_id=delta.generation_id,
            turn_id=delta.turn_id,
            node_id=delta.node_id,
            node_revision=delta.node_revision,
            response_locale=delta.response_locale,
            delta=delta.text,
        ),
    )


def _ensure_open_generation(stream: dict[str, object], generation_id: str) -> None:
    if stream["generation_id"] != generation_id:
        raise _error(
            "presentation_stream_superseded", "Presentation stream generation is superseded."
        )
    if stream["status"] != "open":
        raise _error("presentation_stream_superseded", "Presentation stream is already terminal.")


def _chunk_limits(connection: object, stream_id: str) -> tuple[int, int]:
    rows = connection.execute(  # type: ignore[union-attr]
        select(PresentationStreamChunkRow.byte_size).where(
            PresentationStreamChunkRow.stream_id == stream_id
        )
    ).all()
    return len(rows), sum(int(row[0]) for row in rows)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="presentation")


__all__ = (
    "MAX_PRESENTATION_BYTES",
    "MAX_PRESENTATION_CHUNKS",
    "MAX_PRESENTATION_CHUNK_BYTES",
    "PRESENTATION_TERMINAL_RETENTION",
    "PresentationCursorExpiredError",
    "PresentationStreamRepository",
)
