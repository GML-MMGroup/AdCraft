"""Best-effort presentation delivery around authoritative Agent operations."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from app.schemas.agent_runtime import AgentPresentationDeltaV1

from app.persistence.agent_canvas_presentation_repository import PresentationStreamRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_presentation import (
    PresentationStreamEventV1,
    PresentationStreamMetadataV1,
    PresentationStreamResetV1,
    PresentationTimingV1,
    SafePresentationDeltaV1,
)


class PresentationStreamPublisher:
    """Publish safe display text without becoming an authoring authority."""

    def __init__(self, repository: PresentationStreamRepository) -> None:
        self._repository = repository
        # One stream can receive several sequential Agent runs (for example a
        # chat turn's intent and next-action calls); attempts are per run.
        self._runtime_attempt: dict[str, tuple[str, int]] = {}
        self._reasoning_streams: set[str] = set()
        self._answer_text: dict[str, str] = {}

    def create_assistant_stream(
        self,
        *,
        workflow_id: str,
        turn_id: str,
        stream_id: str,
        idempotency_key: str,
        generation_id: str | None = None,
    ) -> PresentationStreamMetadataV1 | None:
        return self._create(
            PresentationStreamMetadataV1(
                stream_id=stream_id,
                workflow_id=workflow_id,
                stream_kind="assistant",
                generation_id=generation_id or turn_id,
                turn_id=turn_id,
                status="open",
            ),
            idempotency_key=idempotency_key,
        )

    def create_prompt_stream(
        self,
        *,
        workflow_id: str,
        node_id: str,
        node_revision: int,
        generation_id: str,
        stream_id: str,
        idempotency_key: str,
    ) -> PresentationStreamMetadataV1 | None:
        return self._create(
            PresentationStreamMetadataV1(
                stream_id=stream_id,
                workflow_id=workflow_id,
                stream_kind="node_prompt",
                generation_id=generation_id,
                node_id=node_id,
                node_revision=node_revision,
                status="open",
            ),
            idempotency_key=idempotency_key,
        )

    def started(self, metadata: PresentationStreamMetadataV1) -> PresentationStreamEventV1 | None:
        return self._safe_event(
            PresentationStreamEventV1(
                stream_id=metadata.stream_id,
                workflow_id=metadata.workflow_id,
                stream_kind=metadata.stream_kind,
                event_type="started",
                sequence_no=metadata.last_sequence_no + 1,
                generation_id=metadata.generation_id,
                turn_id=metadata.turn_id,
                node_id=metadata.node_id,
                node_revision=metadata.node_revision,
            ),
            event_key="started",
        )

    def publish_delta(self, delta: SafePresentationDeltaV1) -> PresentationStreamEventV1 | None:
        try:
            return self._repository.append_chunk(delta)
        except V2PersistenceError:
            return None

    def publish_runtime_delta(
        self,
        workflow_id: str,
        event: AgentPresentationDeltaV1,
    ) -> PresentationStreamEventV1 | None:
        """Resolve runtime stream identity from Python-owned stream metadata.

        Runtime events carry a stream id only as a routing hint.  The stream
        metadata is authoritative for workflow ownership and all generation
        identity fields, so foreign, missing, or terminal streams are ignored.
        """

        if event.stream_id is None:
            return None
        try:
            metadata = self._repository.get(workflow_id, event.stream_id)
        except V2PersistenceError:
            return None
        if metadata.status != "open":
            return None
        stream_id = metadata.stream_id
        # A first-seen retry still clears whatever an unseen earlier attempt left.
        current = self._runtime_attempt.get(stream_id, (event.generation_id, 1))
        separate_reasoning = False
        if current[0] == event.generation_id:
            if event.attempt < current[1]:
                return None
            if event.attempt > current[1]:
                run_digest = sha256(event.generation_id.encode("utf-8")).hexdigest()[:16]
                self.reset(
                    metadata,
                    reason="attempt_restarted",
                    event_key=f"reset:attempt_restarted:{run_digest}:{event.attempt}",
                )
                self._answer_text[stream_id] = ""
                self._reasoning_streams.discard(stream_id)
        else:
            # A later run on the same stream continues the visible thinking.
            separate_reasoning = stream_id in self._reasoning_streams
        self._runtime_attempt[stream_id] = (event.generation_id, event.attempt)
        if event.segment == "reasoning" and separate_reasoning:
            self._publish_runtime_text(metadata, event, "\n\n")
        published = self._publish_runtime_text(metadata, event, event.text)
        if published is not None and event.segment == "answer":
            self._answer_text[stream_id] = self._answer_text.get(stream_id, "") + event.text
        if published is not None and event.segment == "reasoning":
            self._reasoning_streams.add(stream_id)
        return published

    def _publish_runtime_text(
        self,
        metadata: PresentationStreamMetadataV1,
        event: AgentPresentationDeltaV1,
        text: str,
    ) -> PresentationStreamEventV1 | None:
        try:
            delta = SafePresentationDeltaV1(
                stream_id=metadata.stream_id,
                workflow_id=metadata.workflow_id,
                stream_kind=metadata.stream_kind,
                generation_id=metadata.generation_id,
                turn_id=metadata.turn_id,
                node_id=metadata.node_id,
                node_revision=metadata.node_revision,
                response_locale=event.response_locale,
                segment=event.segment,
                text=text,
            )
        except (TypeError, ValueError):
            return None
        return self.publish_delta(delta)

    def answer_text(self, stream_id: str) -> str:
        """Return the accepted answer text for the current stream attempt."""

        return self._answer_text.get(stream_id, "")

    def publish_validated_text(
        self,
        metadata: PresentationStreamMetadataV1,
        text: str,
        *,
        response_locale: str | None = None,
    ) -> tuple[PresentationStreamEventV1, ...]:
        """Publish already validated final text in bounded chunks without another LLM call."""

        result: list[PresentationStreamEventV1] = []
        remaining = text.encode("utf-8")
        while remaining:
            boundary = min(4_096, len(remaining))
            while True:
                try:
                    piece = remaining[:boundary].decode("utf-8")
                    break
                except UnicodeDecodeError:
                    boundary -= 1
            remaining = remaining[boundary:]
            event = self.publish_delta(
                SafePresentationDeltaV1(
                    stream_id=metadata.stream_id,
                    workflow_id=metadata.workflow_id,
                    stream_kind=metadata.stream_kind,
                    generation_id=metadata.generation_id,
                    turn_id=metadata.turn_id,
                    node_id=metadata.node_id,
                    node_revision=metadata.node_revision,
                    response_locale=response_locale,
                    segment="answer",
                    text=piece,
                )
            )
            if event is not None:
                result.append(event)
        return tuple(result)

    def commit(
        self,
        metadata: PresentationStreamMetadataV1,
        *,
        authoritative_id: str,
        content: str,
    ) -> PresentationStreamEventV1 | None:
        try:
            return self._repository.finish(
                metadata.stream_id,
                generation_id=metadata.generation_id,
                authoritative_id=authoritative_id,
                content_digest=sha256(content.encode("utf-8")).hexdigest(),
            )
        except V2PersistenceError:
            return None
        finally:
            self._forget_runtime_state(metadata.stream_id)

    def fail(
        self, metadata: PresentationStreamMetadataV1, error_code: str
    ) -> PresentationStreamEventV1 | None:
        try:
            return self._repository.fail(
                metadata.stream_id,
                generation_id=metadata.generation_id,
                error_code=error_code,
            )
        except V2PersistenceError:
            return None
        finally:
            self._forget_runtime_state(metadata.stream_id)

    def supersede(self, metadata: PresentationStreamMetadataV1) -> PresentationStreamEventV1 | None:
        """Close a stale prompt generation without changing node authority."""

        try:
            return self._repository.supersede(
                metadata.stream_id,
                generation_id=metadata.generation_id,
            )
        except V2PersistenceError:
            return None
        finally:
            self._forget_runtime_state(metadata.stream_id)

    def _forget_runtime_state(self, stream_id: str) -> None:
        self._runtime_attempt.pop(stream_id, None)
        self._reasoning_streams.discard(stream_id)
        self._answer_text.pop(stream_id, None)

    def reset(
        self,
        metadata: PresentationStreamMetadataV1,
        *,
        reason: str,
        event_key: str | None = None,
    ) -> PresentationStreamEventV1 | None:
        """Append a safe presentation reset marker for an open stream."""

        try:
            event = PresentationStreamEventV1(
                stream_id=metadata.stream_id,
                workflow_id=metadata.workflow_id,
                stream_kind=metadata.stream_kind,
                event_type="reset",
                sequence_no=metadata.last_sequence_no + 1,
                generation_id=metadata.generation_id,
                turn_id=metadata.turn_id,
                node_id=metadata.node_id,
                node_revision=metadata.node_revision,
                reset=PresentationStreamResetV1(
                    reason=reason,  # type: ignore[arg-type]
                    resource_kind=("message" if metadata.stream_kind == "assistant" else "prompt"),
                ),
            )
            return self._repository.append_event(
                event,
                event_key=event_key or f"reset:{reason}",
            )
        except (TypeError, ValueError, V2PersistenceError):
            return None

    def get(self, workflow_id: str, stream_id: str) -> PresentationStreamMetadataV1 | None:
        """Best-effort lookup used when fencing an old prompt generation."""

        try:
            return self._repository.get(workflow_id, stream_id)
        except V2PersistenceError:
            return None

    def timing(self, metadata: PresentationStreamMetadataV1, timing: PresentationTimingV1) -> bool:
        """Keep the timing contract available without storing text or sensitive data."""

        try:
            for phase, elapsed_ms in timing.model_dump(exclude_none=True).items():
                self._repository.record_timing(metadata.stream_id, phase, elapsed_ms)
            return True
        except V2PersistenceError:
            return False

    def _create(
        self,
        metadata: PresentationStreamMetadataV1,
        *,
        idempotency_key: str,
    ) -> PresentationStreamMetadataV1 | None:
        try:
            return self._repository.create(metadata, idempotency_key=idempotency_key)
        except V2PersistenceError:
            return None

    def _safe_event(
        self,
        event: PresentationStreamEventV1,
        *,
        event_key: str,
    ) -> PresentationStreamEventV1 | None:
        try:
            return self._repository.append_event(event, event_key=event_key)
        except V2PersistenceError:
            return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def presentation_stream_id(workflow_id: str, generation_id: str) -> str:
    """Derive the stable assistant stream identity used by chat turns."""

    digest = sha256(f"assistant:{workflow_id}:{generation_id}".encode("utf-8")).hexdigest()[:32]
    return f"prs_{digest}"


__all__ = ("PresentationStreamPublisher", "presentation_stream_id")
