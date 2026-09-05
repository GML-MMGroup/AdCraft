"""Prepare Agent Canvas node results without publishing runtime state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import ValidationError

from app.persistence.errors import V2PersistenceError

from app.persistence.agent_canvas_result_publication_repository import (
    AgentCanvasResultPublicationIntentRepository,
)
from app.schemas.agent_canvas_runtime_authority import (
    CanvasResultPublicationIntentV1,
    PreparedNodeResultV2,
    PreparedPostReadyEffectV2,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_node_execution import (
    NodeExecutionContext,
    NodeExecutionOutcome,
)
from app.services.agent_canvas_publication_metadata import (
    project_canvas_publication_metadata,
    PUBLICATION_FAILED_MESSAGE,
)


@dataclass(frozen=True, slots=True)
class ResultPublicationContext:
    member_id: str
    source_snapshot_id: str
    source_snapshot_digest: str


class AgentCanvasOutputPreparationService:
    def __init__(
        self,
        assets: AgentCanvasAssetService,
        *,
        publication_intents: AgentCanvasResultPublicationIntentRepository | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._assets = assets
        self._publication_intents = publication_intents
        self._clock = clock

    def prepare(
        self,
        context: NodeExecutionContext,
        outcome: NodeExecutionOutcome,
        *,
        fingerprint: str,
        publication: ResultPublicationContext | None = None,
    ) -> PreparedNodeResultV2:
        try:
            return self._prepare(context, outcome, fingerprint=fingerprint, publication=publication)
        except ValidationError as error:
            raise V2PersistenceError(
                "node_result_publication_failed",
                PUBLICATION_FAILED_MESSAGE,
                stage="node_result_publication",
            ) from error

    def _prepare(
        self,
        context: NodeExecutionContext,
        outcome: NodeExecutionOutcome,
        *,
        fingerprint: str,
        publication: ResultPublicationContext | None = None,
    ) -> PreparedNodeResultV2:
        effects = _effects(context)
        if outcome.media is not None:
            metadata = project_canvas_publication_metadata(
                context, publication, outcome.media.metadata
            )
            effective_parameters = (
                context.effective_parameters.effective
                if context.effective_parameters is not None
                else context.node.parameters
            )
            publication_intent_id = None
            before_object_publish = None
            if self._publication_intents is not None:
                if publication is None:
                    raise ValueError("Durable media preparation requires publication context.")
                publication_intent_id = _publication_intent_id(
                    context.execution_id,
                    publication.member_id,
                    fingerprint,
                )

                def persist_intent(planned: PreparedNodeResultV2) -> object:
                    now = self._clock()
                    prepared_object = planned.prepared_object
                    if prepared_object is None:
                        raise ValueError("Media publication intent requires an object identity.")
                    return self._publication_intents.create_or_replay(
                        CanvasResultPublicationIntentV1(
                            intent_id=publication_intent_id,
                            workflow_id=context.node.workflow_id,
                            execution_id=context.execution_id,
                            member_id=publication.member_id,
                            node_id=context.node.node_id,
                            logical_result_key=planned.logical_result_key,
                            payload_digest=planned.payload_digest,
                            source_snapshot_id=publication.source_snapshot_id,
                            source_snapshot_digest=publication.source_snapshot_digest,
                            expected_storage_key=prepared_object.storage_key,
                            expected_object_sha256=prepared_object.sha256,
                            planned_result=planned,
                            state="preparing",
                            attempt_count=0,
                            next_attempt_at=now,
                            recovery_deadline=now + timedelta(minutes=5),
                            created_at=now,
                            updated_at=now,
                        )
                    )

                before_object_publish = persist_intent
            prepared = self._assets.prepare_generated_bytes(
                context.node.workflow_id,
                node_id=context.node.node_id,
                execution_id=context.execution_id,
                filename=outcome.media.filename,
                mime_type=outcome.media.mime_type,
                content=outcome.media.content,
                fingerprint=fingerprint,
                source_semantic_role=context.node.semantic_role,
                publication_metadata=metadata,
                require_native_audio=(
                    context.node.node_type == "video"
                    and effective_parameters.get("generate_audio") is True
                ),
                publication_intent_id=publication_intent_id,
                before_object_publish=before_object_publish,
            )
            prepared = prepared.model_copy(
                update={
                    "provider_task_id": outcome.provider_task_id,
                    "post_ready_effects": effects,
                }
            )
            if self._publication_intents is not None:
                if publication_intent_id is None:
                    raise AssertionError("Publication intent identity was not assigned.")
                self._publication_intents.promote_prepared(
                    publication_intent_id,
                    prepared_result=prepared,
                    now=self._clock(),
                )
            return prepared
        structured = outcome.structured_content or {}
        digest = _digest(structured)
        return PreparedNodeResultV2(
            logical_result_key=fingerprint,
            payload_digest=digest,
            structured_content=structured,
            provider_task_id=outcome.provider_task_id,
            post_ready_effects=effects,
        )


def _effects(
    context: NodeExecutionContext,
) -> tuple[PreparedPostReadyEffectV2, ...]:
    if context.node.node_type == "script":
        return (
            PreparedPostReadyEffectV2(
                effect_type="persist_script_document",
                payload={"node_id": context.node.node_id},
            ),
        )
    if context.node.node_type == "text":
        return (
            PreparedPostReadyEffectV2(
                effect_type="persist_text_document",
                payload={"node_id": context.node.node_id},
            ),
        )
    if context.node.node_type in {"image", "video", "audio"}:
        return (
            PreparedPostReadyEffectV2(
                effect_type="advance_storyboard_progression",
                payload={"node_id": context.node.node_id},
            ),
        )
    return ()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _publication_intent_id(execution_id: str, member_id: str, fingerprint: str) -> str:
    identity = f"{execution_id}:{member_id}:{fingerprint}"
    return "publication_intent_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
