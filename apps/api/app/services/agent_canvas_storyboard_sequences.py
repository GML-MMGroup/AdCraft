"""Deterministic sequence planning and bounded storyboard authoring contexts."""

from __future__ import annotations

from math import ceil
from typing import Protocol, cast

from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas_ad_media import ProviderModelCapabilityV2
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardGridAuthoringContextV2,
    StoryboardSequencePlanDraftV2,
    StoryboardVideoAuthoringContextV2,
)
from app.schemas.agent_canvas_creative_session import (
    StoryboardImageSpecialistDraftV2,
    VideoSpecialistDraftV2,
)
from app.schemas.agent_working_documents import (
    AgentAnchorV2,
    AgentDocumentPatchResultV2,
    AgentWorkingDocumentPageV2,
    AgentWorkingDocumentV2,
    AnchorRegistryContentV2,
    InitializeStoryboardPlanPatchV2,
    StoryboardNarrativeSegmentV2,
    StoryboardPlanGlobalParametersV2,
    StoryboardPlanRowV2,
    StoryboardProductionPlanContentV2,
    UpsertAnchorPatchV2,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_working_documents import AgentWorkingDocumentService


class _WorkingDocumentReader(Protocol):
    def get_document(
        self,
        workflow_id: str,
        document_id: str,
    ) -> AgentWorkingDocumentV2: ...

    def list_documents(
        self,
        workflow_id: str,
        *,
        kind: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> AgentWorkingDocumentPageV2: ...

    def get_or_create_storyboard_plan(
        self,
        *,
        workflow_id: str,
        guidance_session_id: str,
        agent_run_id: str,
        content: StoryboardProductionPlanContentV2,
        title: str = "Storyboard Production Plan",
    ) -> AgentWorkingDocumentV2: ...

    def apply_agent_patch(
        self,
        workflow_id: str,
        agent_run_id: str,
        patch: InitializeStoryboardPlanPatchV2,
    ) -> AgentDocumentPatchResultV2: ...


class StoryboardSequenceAuthoringService:
    """Keep sequence timing and reference resolution deterministic."""

    def __init__(
        self,
        *,
        documents: _WorkingDocumentReader,
        events: EventRepository | None = None,
    ) -> None:
        self._documents = documents
        self._events = events

    @staticmethod
    def build_plan_content(
        draft: StoryboardSequencePlanDraftV2,
        capability: ProviderModelCapabilityV2,
    ) -> StoryboardProductionPlanContentV2:
        segment_cap = capability.max_duration_seconds or draft.total_duration_seconds
        segment_count = ceil(draft.total_duration_seconds / segment_cap)
        if len(draft.sequences) != segment_count:
            raise _storyboard_error(
                "The Storyboard plan must provide one sequence per duration segment."
            )

        segments: list[StoryboardNarrativeSegmentV2] = []
        rows: list[StoryboardPlanRowV2] = []
        shot_index = 1
        for order, sequence in enumerate(draft.sequences, start=1):
            start_seconds = min((order - 1) * segment_cap, draft.total_duration_seconds)
            end_seconds = min(order * segment_cap, draft.total_duration_seconds)
            segments.append(
                StoryboardNarrativeSegmentV2(
                    sequence_id=sequence.sequence_id,
                    order=order,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    narrative_goal=sequence.narrative_goal,
                    start_state=sequence.start_state,
                    end_state=sequence.end_state,
                    continuity_from_previous=sequence.continuity_from_previous,
                )
            )
            for row in sequence.rows:
                rows.append(
                    StoryboardPlanRowV2(
                        shot_index=shot_index,
                        sequence_id=sequence.sequence_id,
                        panel_index=row.panel_index,
                        content_beat=row.content_beat,
                        anchor_aliases=row.anchor_aliases,
                        camera_description=row.camera_description,
                    )
                )
                shot_index += 1
        return StoryboardProductionPlanContentV2(
            narrative_outline=draft.narrative_outline,
            global_parameters=StoryboardPlanGlobalParametersV2(
                aspect_ratio=draft.aspect_ratio,
                total_duration_seconds=draft.total_duration_seconds,
                segment_count=segment_count,
            ),
            segments=tuple(segments),
            rows=tuple(rows),
        )

    def build_grid_context(
        self,
        workflow_id: str,
        plan_document_id: str,
        sequence_id: str,
        *,
        style_excerpt: str | None = None,
    ) -> StoryboardGridAuthoringContextV2:
        document = self._documents.get_document(workflow_id, plan_document_id)
        if document.kind != "storyboard_production_plan":
            raise _storyboard_error("The requested document is not a Storyboard plan.")
        content = cast(StoryboardProductionPlanContentV2, document.content)
        sequence = next(
            (item for item in content.segments if item.sequence_id == sequence_id),
            None,
        )
        if sequence is None:
            raise _storyboard_error("The Storyboard sequence was not found.")
        rows = tuple(row for row in content.rows if row.sequence_id == sequence_id)
        required_aliases = tuple(
            dict.fromkeys(alias for row in rows for alias in row.anchor_aliases)
        )
        anchors = self._resolve_anchors(workflow_id, required_aliases)
        return StoryboardGridAuthoringContextV2(
            workflow_id=workflow_id,
            plan_document_id=document.document_id,
            plan_revision=document.revision,
            plan_content_digest=document.content_digest,
            sequence=sequence,
            rows=rows,
            anchors=anchors,
            style_excerpt=style_excerpt,
        )

    def persist_plan(
        self,
        *,
        workflow_id: str,
        guidance_session_id: str,
        agent_run_id: str,
        idempotency_key: str,
        draft: StoryboardSequencePlanDraftV2,
        capability: ProviderModelCapabilityV2,
    ) -> AgentWorkingDocumentV2:
        content = self.build_plan_content(draft, capability)
        document = self._documents.get_or_create_storyboard_plan(
            workflow_id=workflow_id,
            guidance_session_id=guidance_session_id,
            agent_run_id=agent_run_id,
            content=content,
        )
        if document.content != content:
            document = self._documents.apply_agent_patch(
                workflow_id,
                agent_run_id,
                InitializeStoryboardPlanPatchV2(
                    operation="initialize_storyboard_plan",
                    document_id=document.document_id,
                    expected_revision=document.revision,
                    idempotency_key=idempotency_key,
                    content=content,
                ),
            ).document
        if self._events is None:
            raise V2PersistenceError(
                "storyboard_sequence_event_repository_required",
                "Storyboard plan persistence requires the canonical event repository.",
                stage="storyboard_sequence_authoring",
            )
        self._events.append(
            V2EventInsert(
                workflow_id=workflow_id,
                event_type="storyboard_sequence_planned",
                transition_key=(
                    f"storyboard_sequence_planned:{document.document_id}:{document.revision}"
                ),
                created_at=document.updated_at.isoformat(),
                payload={
                    "agent_run_id": agent_run_id,
                    "guidance_session_id": guidance_session_id,
                    "plan_document_id": document.document_id,
                    "plan_revision": document.revision,
                    "sequence_ids": [sequence.sequence_id for sequence in content.segments],
                    "total_duration_seconds": content.global_parameters.total_duration_seconds,
                },
            )
        )
        return document

    def validate_grid_draft(
        self,
        draft: StoryboardImageSpecialistDraftV2,
        context: StoryboardGridAuthoringContextV2,
    ) -> StoryboardImageSpecialistDraftV2:
        if draft.structured_content.narrative_goal != context.sequence.narrative_goal:
            raise _storyboard_error(
                "The Storyboard Grid narrative goal does not match its sequence."
            )
        explicit_source_ids = {reference.source_id for reference in draft.reference_intents}
        required_source_ids = {
            anchor.source_id for anchor in context.anchors if anchor.source_id is not None
        }
        if not required_source_ids <= explicit_source_ids:
            raise _anchor_error(
                "Every resolved Storyboard anchor requires an explicit Draft reference."
            )
        references_by_source = {
            reference.source_id: reference for reference in draft.reference_intents
        }
        for anchor in context.anchors:
            if anchor.source_id is None:
                continue
            expected_role = {
                "subject": "subject_reference",
                "environment": "environment_reference",
                "world_setting": "world_setting_reference",
                "style": "style_reference",
                "composition": "style_composition_reference",
            }[anchor.anchor_type]
            if references_by_source[anchor.source_id].semantic_reference_role != expected_role:
                raise _anchor_error(
                    "Storyboard Draft reference metadata does not match its anchor."
                )
        return draft

    def build_video_context(
        self,
        workflow_id: str,
        plan_document_id: str,
        sequence_id: str,
        *,
        storyboard_grid_node_id: str | None,
        resolved_binding_ids: tuple[str, ...],
        style_excerpt: str | None = None,
    ) -> StoryboardVideoAuthoringContextV2:
        grid_context = self.build_grid_context(
            workflow_id,
            plan_document_id,
            sequence_id,
            style_excerpt=style_excerpt,
        )
        return StoryboardVideoAuthoringContextV2.model_validate(
            {
                **grid_context.model_dump(mode="json"),
                "storyboard_grid_node_id": storyboard_grid_node_id,
                "resolved_binding_ids": resolved_binding_ids,
            }
        )

    def validate_video_draft(
        self,
        draft: VideoSpecialistDraftV2,
        context: StoryboardVideoAuthoringContextV2,
    ) -> VideoSpecialistDraftV2:
        planned_duration = context.sequence.end_seconds - context.sequence.start_seconds
        if abs(draft.structured_content.duration_seconds - planned_duration) > 0.001:
            raise _storyboard_error(
                "The Video Draft duration does not match its Storyboard sequence."
            )
        return draft

    def _resolve_anchors(
        self,
        workflow_id: str,
        aliases: tuple[str, ...],
    ) -> tuple:
        if not aliases:
            return ()
        page = self._documents.list_documents(
            workflow_id,
            kind="anchor_registry",
            limit=1,
        )
        if not page.items:
            raise _anchor_error("The Anchor Registry was not found.")
        registry = cast(AnchorRegistryContentV2, page.items[0].content)
        anchors_by_alias = {anchor.alias: anchor for anchor in registry.anchors}
        resolved = []
        for alias in aliases:
            anchor = anchors_by_alias.get(alias)
            if anchor is None or anchor.availability != "available" or anchor.source_id is None:
                raise _anchor_error(f"Storyboard anchor {alias} is not available for authoring.")
            resolved.append(anchor)
        return tuple(resolved)


class GuidedAnchorRegistryService:
    """Lazily register approved foundations without creating runtime inputs."""

    _ROLE_MAPPING = {
        "world_setting": ("W", "world_setting"),
        "product": ("P", "subject"),
        "prop": ("R", "subject"),
        "character": ("C", "subject"),
        "scene": ("E", "environment"),
    }

    def __init__(
        self,
        *,
        workflows,
        documents: AgentWorkingDocumentService,
    ) -> None:
        self._workflows = workflows
        self._documents = documents

    def sync_approved_nodes(
        self,
        *,
        workflow_id: str,
        guidance_session_id: str,
        agent_run_id: str,
    ) -> AgentWorkingDocumentV2:
        document = self._documents.get_or_create_anchor_registry(
            workflow_id=workflow_id,
            guidance_session_id=guidance_session_id,
            agent_run_id=agent_run_id,
        )
        content = cast(AnchorRegistryContentV2, document.content)
        existing_sources = {
            anchor.source_id for anchor in content.anchors if anchor.source_id is not None
        }
        aliases = {anchor.alias for anchor in content.anchors}
        for node in self._workflows.get_workflow(workflow_id).nodes:
            mapping = self._ROLE_MAPPING.get(node.creative_role)
            if mapping is None or node.status != "ready" or node.node_id in existing_sources:
                continue
            prefix, anchor_type = mapping
            alias = _next_alias(prefix, aliases)
            document = self._documents.apply_agent_patch(
                workflow_id,
                agent_run_id,
                UpsertAnchorPatchV2(
                    operation="upsert_anchor",
                    document_id=document.document_id,
                    expected_revision=document.revision,
                    idempotency_key=f"anchor:{node.node_id}:{node.revision}",
                    anchor=AgentAnchorV2(
                        alias=alias,
                        anchor_type=anchor_type,
                        display_name=node.title,
                        summary=(
                            node.summary_prompt
                            or node.generation_prompt
                            or f"Approved {node.creative_role} foundation."
                        ),
                        source_kind="node",
                        source_id=node.node_id,
                        availability="available",
                    ),
                ),
            ).document
            aliases.add(alias)
            existing_sources.add(node.node_id)
        return document


def _storyboard_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_sequence_invalid",
        message,
        stage="storyboard_sequence_authoring",
    )


def _anchor_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_anchor_resolution_failed",
        message,
        stage="storyboard_sequence_authoring",
    )


def _next_alias(prefix: str, aliases: set[str]) -> str:
    for index in range(1, 100):
        candidate = f"{prefix}{index:02d}"
        if candidate not in aliases:
            return candidate
    raise _anchor_error("The Anchor Registry alias range is exhausted.")
