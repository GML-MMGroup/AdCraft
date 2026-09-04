"""Compile bounded target-scoped context from one canonical World Setting."""

from __future__ import annotations

import hashlib
import json
from typing import cast

from pydantic import ValidationError

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ResolvedTextBindingInputV2
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_world_setting import (
    WorldSettingContextAudienceV2,
    WorldSettingContextEnvelopeV2,
    WorldSettingDocumentV2,
    WorldSettingResolvedInputV2,
)


WORLD_SETTING_CONTEXT_AUDIENCES = (
    "script",
    "product",
    "prop",
    "character",
    "scene",
    "storyboard",
    "video",
    "bgm",
)

_COMPILER_ID = "adcraft.world-setting-context.v2"
_AUDIENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "script": ("world_rules", "visual_continuity"),
    "product": ("world_rules", "visual_continuity"),
    "prop": ("world_rules", "visual_continuity"),
    "character": ("world_rules", "visual_continuity"),
    "scene": ("world_rules", "visual_continuity"),
    "storyboard": ("world_rules", "visual_continuity"),
    "video": ("world_rules", "visual_continuity"),
    "bgm": ("world_rules",),
}


class WorldSettingContextCompilerV2:
    """Select canonical world facts for one audience without an Agent call."""

    @property
    def compiler_id(self) -> str:
        return _COMPILER_ID

    @property
    def compiler_digest(self) -> str:
        return _digest(
            {
                "compiler_id": _COMPILER_ID,
                "audience_fields": _AUDIENCE_FIELDS,
            }
        )

    def compile(
        self,
        document: WorldSettingDocumentV2,
        *,
        source_node_id: str,
        source_node_revision: int,
        audience: str,
    ) -> WorldSettingContextEnvelopeV2:
        fields = _AUDIENCE_FIELDS.get(audience)
        if fields is None:
            raise V2PersistenceError(
                "world_setting_context_audience_invalid",
                "World Setting context audience is not supported.",
                stage="world_setting_context_compiler",
                details={"target_audience": audience},
            )
        validated_audience = cast(WorldSettingContextAudienceV2, audience)
        content_digest = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
        core_digest = _digest(document.core.model_dump(mode="json"))
        payload = {
            "context_kind": "world_setting_context_v2",
            "source_node_id": source_node_id,
            "source_node_revision": source_node_revision,
            "source_content_digest": content_digest,
            "source_core_digest": core_digest,
            "target_audience": validated_audience,
            "shared_summary": (
                f"Premise: {document.core.premise}\nEra and place: {document.core.era_and_place}"
            ),
            "relevant_world_rules": (document.core.world_rules if "world_rules" in fields else ()),
            "relevant_visual_continuity": (
                document.core.visual_continuity if "visual_continuity" in fields else ()
            ),
            "compiler_id": self.compiler_id,
            "compiler_digest": self.compiler_digest,
        }
        return WorldSettingContextEnvelopeV2(
            **payload,
            context_digest=_digest(payload),
        )


class WorldSettingContextResolverV2:
    """Resolve canonical documents and compile only the requested audience."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        compiler: WorldSettingContextCompilerV2 | None = None,
    ) -> None:
        self._workflows = workflows
        self._compiler = compiler or WorldSettingContextCompilerV2()

    def resolve_for_guidance(
        self,
        *,
        workflow_id: str,
        session: GuidedSessionStateV2,
        audience: str,
    ) -> WorldSettingContextEnvelopeV2 | None:
        topics = tuple(
            topic
            for topic in session.topics
            if topic.topic_kind == "world_setting" and topic.status == "selected"
        )
        if not topics:
            return None
        if len(topics) != 1 or len(topics[0].related_node_ids) != 1:
            raise _context_error(
                "Selected World Setting source is ambiguous.",
                target_audience=audience,
            )
        node = self._workflows.get_node(workflow_id, topics[0].related_node_ids[0])
        if (
            node.node_type != "text"
            or node.creative_role != "world_setting"
            or node.status != "ready"
        ):
            raise _context_error(
                "Selected World Setting Text Node is not Ready.",
                source_node_id=node.node_id,
                source_node_revision=node.revision,
                target_audience=audience,
            )
        try:
            document = _document(node.structured_content)
        except V2PersistenceError as error:
            raise _context_error(
                "Canonical World Setting content is unavailable.",
                source_node_id=node.node_id,
                source_node_revision=node.revision,
                target_audience=audience,
            ) from error
        return self._compiler.compile(
            document,
            source_node_id=node.node_id,
            source_node_revision=node.revision,
            audience=audience,
        )

    def resolve_for_run(
        self,
        *,
        workflow_id: str,
        source: ResolvedTextBindingInputV2,
    ) -> WorldSettingResolvedInputV2:
        self._workflows.get_workflow(workflow_id)
        audience = str(source.binding_metadata.get("target_audience") or "")
        try:
            document = _document(source.source_structured_content)
        except V2PersistenceError as error:
            raise _context_error(
                "Canonical World Setting content is unavailable.",
                source_node_id=source.source_node_id,
                source_node_revision=source.source_node_revision,
                target_audience=audience,
            ) from error
        content_digest = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
        if content_digest != source.content_digest:
            raise _context_error(
                "Frozen World Setting content identity is inconsistent.",
                source_node_id=source.source_node_id,
                source_node_revision=source.source_node_revision,
                target_audience=audience,
            )
        context = self._compiler.compile(
            document,
            source_node_id=source.source_node_id,
            source_node_revision=source.source_node_revision,
            audience=audience,
        )
        return WorldSettingResolvedInputV2(
            binding_id=source.binding_id,
            source_node_id=context.source_node_id,
            source_node_revision=context.source_node_revision,
            source_content_digest=context.source_content_digest,
            source_core_digest=context.source_core_digest,
            required=True,
            display_order=source.display_order,
            target_audience=context.target_audience,
            compiler_id=context.compiler_id,
            compiler_digest=context.compiler_digest,
            context_digest=context.context_digest,
            context=context,
        )


def _document(value: object) -> WorldSettingDocumentV2:
    try:
        return WorldSettingDocumentV2.model_validate(value)
    except (TypeError, ValueError, ValidationError) as error:
        raise _context_error("Canonical World Setting content is unavailable.") from error


def _context_error(message: str, **details: object) -> V2PersistenceError:
    return V2PersistenceError(
        "world_setting_context_unavailable",
        message,
        stage="world_setting_context_resolver",
        details={"retryable": True, **details},
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
