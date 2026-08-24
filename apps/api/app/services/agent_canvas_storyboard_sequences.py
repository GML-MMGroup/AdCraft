"""Deterministic sequence planning and bounded storyboard authoring contexts."""

from __future__ import annotations

from hashlib import sha256
from math import ceil
from typing import Literal, Protocol, cast

from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas_ad_media import ProviderModelCapabilityV2
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardGridAuthoringContextV2,
    StoryboardSegmentMaterializationDraftV2,
    StoryboardSegmentAuthoringContextV2,
    StoryboardSequenceAuthorityPlanV2,
    StoryboardSequenceOutlineDraftV2,
    StoryboardSequencePlanDraftV2,
    StoryboardSequenceRowDraftV2,
    StoryboardVideoAuthoringContextV2,
)
from app.schemas.agent_canvas_creative_session import (
    StoryboardImageSpecialistDraftV2,
    VideoSpecialistDraftV2,
)
from app.schemas.agent_working_documents import (
    AgentAnchorSemanticRoleV3,
    AgentAnchorSourceV3,
    AgentAnchorV3,
    AnchorAcceptanceEvidenceV1,
    AnchorRegistryContentV3,
    AgentDocumentMutationPlanV3,
    AgentDocumentPatchV2,
    AgentAnchorV2,
    AgentDocumentPatchResultV2,
    AgentWorkingDocumentPageV2,
    AgentWorkingDocumentV2,
    AttachStoryboardNodePatchV2,
    AttachVideoNodePatchV2,
    AnchorRegistryContentV2,
    FreezeStoryboardVisualAnchorPatchV2,
    InitializeStoryboardPlanPatchV2,
    MaterializeStoryboardSegmentPatchV2,
    StoryboardNarrativeSegmentV2,
    StoryboardPlanGlobalParametersV2,
    StoryboardPlanRowV2,
    StoryboardProductionPlanContentV2,
    StoryboardProductionPlanContentV3,
    StoryboardPlannedNodeV3,
    StoryboardSegmentMaterializationV2,
    StoryboardSegmentMaterializationV3,
    StoryboardVisualAnchorV2,
    StoryboardVisualAnchorV3,
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
        patch: AgentDocumentPatchV2,
    ) -> AgentDocumentPatchResultV2: ...


class _WorkflowReader(Protocol):
    def get_node(self, workflow_id: str, node_id: str): ...


class StoryboardSequenceAuthoringService:
    """Keep sequence timing and reference resolution deterministic."""

    def __init__(
        self,
        *,
        documents: _WorkingDocumentReader,
        events: EventRepository | None = None,
        workflows: _WorkflowReader | None = None,
    ) -> None:
        self._documents = documents
        self._events = events
        self._workflows = workflows

    def list_plans(self, workflow_id: str) -> AgentWorkingDocumentPageV2:
        return self._documents.list_documents(
            workflow_id,
            kind="storyboard_production_plan",
            limit=20,
        )

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

    @staticmethod
    def build_outline_content(
        draft: StoryboardSequenceOutlineDraftV2,
        authority_plan: StoryboardSequenceAuthorityPlanV2,
    ) -> StoryboardProductionPlanContentV2:
        if draft.aspect_ratio != authority_plan.aspect_ratio or (
            draft.total_duration_seconds != authority_plan.total_duration_seconds
        ):
            raise _storyboard_error("Storyboard outline parameters do not match authority.")
        if len(draft.segments) != len(authority_plan.windows):
            raise _storyboard_error("Storyboard outline count does not match authority.")
        segments: list[StoryboardNarrativeSegmentV2] = []
        for index, (item, window) in enumerate(zip(draft.segments, authority_plan.windows)):
            if item.order != window.order:
                raise _storyboard_error("Storyboard outline order does not match authority.")
            if item.start_seconds != window.start_seconds or item.end_seconds != window.end_seconds:
                raise _storyboard_error("Storyboard outline timing does not match authority.")
            if index and not item.continuity_from_previous:
                raise _storyboard_error("Later storyboard segments require prior-state continuity.")
            segments.append(
                StoryboardNarrativeSegmentV2(
                    sequence_id=f"sequence-{window.order}",
                    order=window.order,
                    start_seconds=window.start_seconds,
                    end_seconds=window.end_seconds,
                    narrative_goal=item.narrative_goal,
                    start_state=item.start_state,
                    end_state=item.end_state,
                    continuity_from_previous=item.continuity_from_previous,
                    terminal_policy=(
                        "close" if window.order == len(authority_plan.windows) else "continue"
                    ),
                )
            )
        return StoryboardProductionPlanContentV2(
            narrative_outline=draft.narrative_outline,
            global_parameters=StoryboardPlanGlobalParametersV2(
                aspect_ratio=authority_plan.aspect_ratio,
                total_duration_seconds=authority_plan.total_duration_seconds,
                segment_count=len(authority_plan.windows),
            ),
            segments=tuple(segments),
            rows=(),
            segment_materializations=tuple(
                StoryboardSegmentMaterializationV2(sequence_id=item.sequence_id)
                for item in segments
            ),
        )

    @staticmethod
    def materialize_segment_content(
        content: StoryboardProductionPlanContentV2,
        sequence_id: str,
        draft: StoryboardSegmentMaterializationDraftV2,
    ) -> StoryboardProductionPlanContentV2:
        segment = next(
            (item for item in content.segments if item.sequence_id == sequence_id),
            None,
        )
        if segment is None:
            raise _storyboard_error("Storyboard sequence was not found.")
        existing = tuple(row for row in content.rows if row.sequence_id == sequence_id)
        if existing:
            raise _storyboard_error("Storyboard sequence is already materialized.")
        rows_by_sequence = {
            item.sequence_id: tuple(
                row for row in content.rows if row.sequence_id == item.sequence_id
            )
            for item in content.segments
        }
        rows_by_sequence[sequence_id] = tuple(
            StoryboardPlanRowV2(
                shot_index=1,
                sequence_id=sequence_id,
                panel_index=row.panel_index,
                content_beat=row.content_beat,
                anchor_aliases=row.anchor_aliases,
                camera_description=row.camera_description,
            )
            for row in draft.rows
        )
        rows: list[StoryboardPlanRowV2] = []
        for item in content.segments:
            for row in rows_by_sequence[item.sequence_id]:
                rows.append(row.model_copy(update={"shot_index": len(rows) + 1}))
        materializations = content.segment_materializations or tuple(
            StoryboardSegmentMaterializationV2(
                sequence_id=item.sequence_id,
                status=("materialized" if rows_by_sequence[item.sequence_id] else "pending"),
                generation_prompt=None,
            )
            for item in content.segments
        )
        materializations = tuple(
            item.model_copy(
                update={
                    "status": "materialized",
                    "generation_prompt": draft.generation_prompt,
                }
            )
            if item.sequence_id == sequence_id
            else item
            for item in materializations
        )
        return content.model_copy(
            update={
                "rows": tuple(rows),
                "segment_materializations": materializations,
                "materialized_panel_cursor": len(rows),
            }
        )

    @staticmethod
    def plan_materialized_sequence_v3(
        content: StoryboardProductionPlanContentV3,
        sequence_id: str,
        draft: StoryboardSegmentMaterializationDraftV2,
        *,
        planned_node: StoryboardPlannedNodeV3 | None = None,
        materialization_id: str | None = None,
    ) -> StoryboardProductionPlanContentV3:
        """Plan one authoritative nine-row sequence without runtime mirrors."""

        sequence_ids = tuple(item.sequence_id for item in content.segments)
        if sequence_id not in sequence_ids:
            raise _storyboard_authority_error("Storyboard sequence was not found.")
        if planned_node is not None and (
            planned_node.sequence_id != sequence_id or planned_node.node_role != "storyboard_grid"
        ):
            raise _storyboard_authority_error("The planned Grid Node does not match its sequence.")
        materializations = content.segment_materializations
        if not materializations:
            if content.rows:
                raise _storyboard_authority_error(
                    "Storyboard sequence materialization records are missing."
                )
            materializations = tuple(
                StoryboardSegmentMaterializationV3(
                    sequence_id=item,
                    materialization_id=f"storyboard-segment:{item}",
                )
                for item in sequence_ids
            )
        if tuple(item.sequence_id for item in materializations) != sequence_ids:
            raise _storyboard_authority_error(
                "Storyboard sequence materialization records are out of date."
            )
        current_materialization = next(
            item for item in materializations if item.sequence_id == sequence_id
        )
        existing_rows = tuple(row for row in content.rows if row.sequence_id == sequence_id)
        existing_node = next(
            (
                record
                for record in content.planned_nodes
                if record.sequence_id == sequence_id and record.node_role == "storyboard_grid"
            ),
            None,
        )
        if existing_rows or current_materialization.status == "materialized":
            expected_prompt = _sequence_local_generation_prompt(
                content,
                sequence_id,
                draft.generation_prompt,
                rows=draft.rows,
            )
            if (
                current_materialization.status != "materialized"
                or expected_prompt != current_materialization.generation_prompt
                or len(existing_rows) != 9
                or any(
                    row.content_beat != draft_row.content_beat
                    or row.camera_description != draft_row.camera_description
                    or row.panel_index != draft_row.panel_index
                    for row, draft_row in zip(existing_rows, draft.rows)
                )
                or (planned_node is not None and existing_node != planned_node)
            ):
                raise _storyboard_authority_error(
                    "Storyboard sequence materialization replay does not match authority."
                )
            return content
        if existing_node is not None:
            raise _storyboard_authority_error("Storyboard Grid Node is already planned.")
        sequence = next(item for item in content.segments if item.sequence_id == sequence_id)
        previous = _previous_sequence(content, sequence)
        if previous is not None:
            _ensure_adjacent_sequence_is_distinct(
                content,
                sequence,
                draft,
            )
        generation_prompt = _sequence_local_generation_prompt(
            content,
            sequence_id,
            draft.generation_prompt,
            rows=draft.rows,
        )
        rows_by_sequence = {
            item.sequence_id: tuple(
                row for row in content.rows if row.sequence_id == item.sequence_id
            )
            for item in content.segments
        }
        rows_by_sequence[sequence_id] = tuple(
            StoryboardPlanRowV2(
                shot_index=1,
                sequence_id=sequence_id,
                panel_index=row.panel_index,
                content_beat=row.content_beat,
                anchor_aliases=row.anchor_aliases,
                camera_description=row.camera_description,
            )
            for row in draft.rows
        )
        rows: list[StoryboardPlanRowV2] = []
        for segment in content.segments:
            for row in rows_by_sequence[segment.sequence_id]:
                rows.append(row.model_copy(update={"shot_index": len(rows) + 1}))
        try:
            resolved_materialization_id = (
                materialization_id or current_materialization.materialization_id
            )
            if resolved_materialization_id != current_materialization.materialization_id:
                current_materialization = current_materialization.model_copy(
                    update={"materialization_id": resolved_materialization_id}
                )
            materializations = tuple(
                current_materialization.model_copy(
                    update={
                        "status": "materialized",
                        "generation_prompt": generation_prompt,
                    }
                )
                if item.sequence_id == sequence_id
                else item
                for item in materializations
            )
            segments = tuple(
                item.model_copy(
                    update={"continuity_from_previous": _continuity_handoff(content, sequence)}
                )
                if item.sequence_id == sequence_id and previous is not None
                else item
                for item in content.segments
            )
            return StoryboardProductionPlanContentV3.model_validate(
                {
                    **content.model_dump(mode="json"),
                    "segments": [item.model_dump(mode="json") for item in segments],
                    "rows": [row.model_dump(mode="json") for row in rows],
                    "segment_materializations": [
                        item.model_dump(mode="json") for item in materializations
                    ],
                    "planned_nodes": [
                        *(item.model_dump(mode="json") for item in content.planned_nodes),
                        *(
                            (planned_node.model_dump(mode="json"),)
                            if planned_node is not None
                            else ()
                        ),
                    ],
                }
            )
        except ValueError as error:
            raise _storyboard_authority_error(
                "Storyboard Production Plan invariants are invalid."
            ) from error

    @staticmethod
    def derived_materialized_panel_cursor(content: StoryboardProductionPlanContentV3) -> int:
        """Project the retired cursor from contiguous committed plan records."""

        materialized = {row.sequence_id for row in content.rows}
        contiguous = 0
        for segment in content.segments:
            if segment.sequence_id not in materialized:
                break
            contiguous += 1
        return contiguous * 9

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

    def build_segment_context(
        self,
        workflow_id: str,
        plan_document_id: str,
        sequence_id: str,
        *,
        style_excerpt: str | None = None,
    ) -> StoryboardSegmentAuthoringContextV2:
        document = self._documents.get_document(workflow_id, plan_document_id)
        if document.kind != "storyboard_production_plan":
            raise _storyboard_error("The requested document is not a Storyboard plan.")
        content = cast(StoryboardProductionPlanContentV2, document.content)
        return self.build_segment_context_from_content(
            workflow_id,
            document.document_id,
            document.revision,
            document.content_digest,
            content,
            sequence_id,
            style_excerpt=style_excerpt,
        )

    def build_segment_context_from_content(
        self,
        workflow_id: str,
        plan_document_id: str,
        plan_revision: int,
        plan_content_digest: str,
        content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
        sequence_id: str,
        *,
        style_excerpt: str | None = None,
    ) -> StoryboardSegmentAuthoringContextV2:
        """Build one segment context from validated, not-yet-persisted plan content."""

        sequence = next(
            (item for item in content.segments if item.sequence_id == sequence_id),
            None,
        )
        if sequence is None:
            raise _storyboard_error("The Storyboard sequence was not found.")
        aliases = tuple(
            dict.fromkeys(
                alias
                for row in content.rows
                if row.sequence_id == sequence_id
                for alias in row.anchor_aliases
            )
        )
        prior = content.segments[sequence.order - 2] if sequence.order > 1 else None
        anchors = self._resolve_anchors(workflow_id, aliases)
        if not aliases:
            page = self._documents.list_documents(
                workflow_id,
                kind="anchor_registry",
                limit=1,
            )
            anchors = _available_anchor_projection(page.items[0].content) if page.items else ()
        return StoryboardSegmentAuthoringContextV2(
            workflow_id=workflow_id,
            plan_document_id=plan_document_id,
            plan_revision=plan_revision,
            plan_content_digest=plan_content_digest,
            sequence=sequence,
            prior_end_state=prior.end_state if prior is not None else None,
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

    def persist_outline(
        self,
        *,
        workflow_id: str,
        guidance_session_id: str,
        agent_run_id: str,
        idempotency_key: str,
        draft: StoryboardSequenceOutlineDraftV2,
        authority_plan: StoryboardSequenceAuthorityPlanV2,
    ) -> AgentWorkingDocumentV2:
        content = self.build_outline_content(draft, authority_plan)
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
        self._append_event(
            workflow_id=workflow_id,
            document=document,
            agent_run_id=agent_run_id,
            guidance_session_id=guidance_session_id,
            event_type="storyboard_sequence_outline_planned",
            transition_key=(
                f"storyboard_sequence_outline_planned:{document.document_id}:{document.revision}"
            ),
            payload={
                "sequence_ids": [item.sequence_id for item in content.segments],
                "total_duration_seconds": content.global_parameters.total_duration_seconds,
            },
        )
        return document

    def persist_segment(
        self,
        *,
        workflow_id: str,
        plan_document_id: str,
        sequence_id: str,
        agent_run_id: str,
        idempotency_key: str,
        draft: StoryboardSegmentMaterializationDraftV2,
    ) -> AgentWorkingDocumentV2:
        document = self._documents.get_document(workflow_id, plan_document_id)
        if document.kind != "storyboard_production_plan":
            raise _storyboard_error("The requested document is not a Storyboard plan.")
        content = cast(StoryboardProductionPlanContentV2, document.content)
        segment = next(
            (item for item in content.segments if item.sequence_id == sequence_id),
            None,
        )
        if segment is None:
            raise _storyboard_error("Storyboard sequence was not found.")
        if segment.order > 1:
            previous = content.segments[segment.order - 2]
            previous_state = previous.end_state.strip()
            if previous_state not in segment.start_state and previous_state not in (
                segment.continuity_from_previous or ""
            ):
                raise _storyboard_error("Storyboard segment does not preserve the prior end state.")
        rows = tuple(
            StoryboardPlanRowV2(
                shot_index=index,
                sequence_id=sequence_id,
                panel_index=row.panel_index,
                content_beat=row.content_beat,
                anchor_aliases=row.anchor_aliases,
                camera_description=row.camera_description,
            )
            for index, row in enumerate(draft.rows, start=1)
        )
        updated = self._documents.apply_agent_patch(
            workflow_id,
            agent_run_id,
            MaterializeStoryboardSegmentPatchV2(
                operation="materialize_storyboard_segment",
                document_id=document.document_id,
                expected_revision=document.revision,
                idempotency_key=idempotency_key,
                sequence_id=sequence_id,
                rows=rows,
                generation_prompt=draft.generation_prompt,
            ),
        ).document
        self._append_event(
            workflow_id=workflow_id,
            document=updated,
            agent_run_id=agent_run_id,
            guidance_session_id=updated.guidance_session_id,
            event_type="storyboard_segment_materialized",
            transition_key=(
                f"storyboard_segment_materialized:{updated.document_id}:"
                f"{sequence_id}:{updated.revision}"
            ),
            payload={"sequence_id": sequence_id, "panel_count": 9},
        )
        self._append_event(
            workflow_id=workflow_id,
            document=updated,
            agent_run_id=agent_run_id,
            guidance_session_id=updated.guidance_session_id,
            event_type="storyboard_sequence_materialized",
            transition_key=(
                f"storyboard_sequence_materialized:{updated.document_id}:"
                f"{sequence_id}:{updated.revision}"
            ),
            payload={"sequence_id": sequence_id, "panel_count": 9},
        )
        return updated

    def freeze_visual_anchor(
        self,
        *,
        workflow_id: str,
        plan_document_id: str,
        grid_node_id: str,
        agent_run_id: str,
        idempotency_key: str,
        asset_version_id: str | None = None,
        acceptance_evidence_id: str | None = None,
    ) -> AgentWorkingDocumentV2:
        if self._workflows is None:
            raise V2PersistenceError(
                "storyboard_sequence_workflow_repository_required",
                "Storyboard visual-anchor freezing requires the workflow repository.",
                stage="storyboard_sequence_authoring",
            )
        node = self._workflows.get_node(workflow_id, grid_node_id)
        if (
            node.node_type != "image"
            or node.creative_role != "storyboard_sequence"
            or node.status != "ready"
            or node.output_asset_id is None
        ):
            raise V2PersistenceError(
                "storyboard_visual_anchor_not_ready",
                "Grid 1 must have a Ready image Asset before later grids are authored.",
                stage="storyboard_sequence_authoring",
            )
        document = self._documents.get_document(workflow_id, plan_document_id)
        content = document.content
        if isinstance(content, StoryboardProductionPlanContentV3):
            if content.visual_anchor is not None:
                if (
                    content.visual_anchor.node_id == grid_node_id
                    and content.visual_anchor.asset_id == node.output_asset_id
                    and content.visual_anchor.asset_version_id == asset_version_id
                    and content.visual_anchor.acceptance_evidence_id == acceptance_evidence_id
                ):
                    return document
                raise _storyboard_error("Storyboard visual anchor is already frozen.")
            if not asset_version_id or not acceptance_evidence_id:
                raise _storyboard_authority_error(
                    "Storyboard V3 visual anchor requires exact Asset and acceptance evidence."
                )
            sequence_id = next(
                (
                    record.sequence_id
                    for record in content.planned_nodes
                    if record.node_role == "storyboard_grid" and record.node_id == grid_node_id
                ),
                None,
            )
            if sequence_id is None:
                raise _storyboard_authority_error(
                    "Storyboard visual anchor does not belong to the current Plan."
                )
            updated = self._documents.commit_content_mutation(
                workflow_id=workflow_id,
                agent_run_id=agent_run_id,
                document_id=document.document_id,
                expected_revision=document.revision,
                operation="freeze_storyboard_visual_anchor",
                idempotency_key=idempotency_key,
                next_content=content.model_copy(
                    update={
                        "visual_anchor": StoryboardVisualAnchorV3(
                            sequence_id=sequence_id,
                            node_id=node.node_id,
                            node_revision=node.revision,
                            asset_id=node.output_asset_id,
                            asset_version_id=asset_version_id,
                            acceptance_evidence_id=acceptance_evidence_id,
                        )
                    }
                ),
            )
            self._append_event(
                workflow_id=workflow_id,
                document=updated,
                agent_run_id=agent_run_id,
                guidance_session_id=updated.guidance_session_id,
                event_type="storyboard_visual_anchor_frozen",
                transition_key=f"storyboard_visual_anchor_frozen:{document.document_id}",
                payload={"node_id": node.node_id, "asset_id": node.output_asset_id},
            )
            return updated
        content = cast(StoryboardProductionPlanContentV2, content)
        if content.visual_anchor is not None:
            if (
                content.visual_anchor.node_id == grid_node_id
                and content.visual_anchor.asset_id == node.output_asset_id
            ):
                return document
            raise _storyboard_error("Storyboard visual anchor is already frozen.")
        updated = self._documents.apply_agent_patch(
            workflow_id,
            agent_run_id,
            FreezeStoryboardVisualAnchorPatchV2(
                operation="freeze_storyboard_visual_anchor",
                document_id=document.document_id,
                expected_revision=document.revision,
                idempotency_key=idempotency_key,
                visual_anchor=StoryboardVisualAnchorV2(
                    node_id=node.node_id,
                    asset_id=node.output_asset_id,
                    node_revision=node.revision,
                    document_revision=document.revision,
                ),
            ),
        ).document
        self._append_event(
            workflow_id=workflow_id,
            document=updated,
            agent_run_id=agent_run_id,
            guidance_session_id=updated.guidance_session_id,
            event_type="storyboard_visual_anchor_frozen",
            transition_key=f"storyboard_visual_anchor_frozen:{document.document_id}",
            payload={"node_id": node.node_id, "asset_id": node.output_asset_id},
        )
        return updated

    def attach_grid_node(
        self,
        *,
        workflow_id: str,
        plan_document_id: str,
        sequence_id: str,
        node_id: str,
        agent_run_id: str,
        idempotency_key: str,
    ) -> AgentWorkingDocumentV2:
        document = self._documents.get_document(workflow_id, plan_document_id)
        content = document.content
        if isinstance(content, StoryboardProductionPlanContentV3):
            return self._attach_v3_node(
                document,
                content,
                sequence_id=sequence_id,
                node_id=node_id,
                node_role="storyboard_grid",
                agent_run_id=agent_run_id,
                idempotency_key=idempotency_key,
            )
        content = cast(StoryboardProductionPlanContentV2, content)
        existing = next(
            (
                item
                for item in content.node_records
                if item.sequence_id == sequence_id and item.node_role == "storyboard_grid"
            ),
            None,
        )
        if existing is not None:
            if existing.node_id == node_id:
                return document
            raise _storyboard_error("Storyboard sequence already owns another Grid Node.")
        return self._documents.apply_agent_patch(
            workflow_id,
            agent_run_id,
            AttachStoryboardNodePatchV2(
                operation="attach_storyboard_node",
                document_id=document.document_id,
                expected_revision=document.revision,
                idempotency_key=idempotency_key,
                sequence_id=sequence_id,
                node_id=node_id,
            ),
        ).document

    def attach_video_node(
        self,
        *,
        workflow_id: str,
        plan_document_id: str,
        sequence_id: str,
        node_id: str,
        agent_run_id: str,
        idempotency_key: str,
    ) -> AgentWorkingDocumentV2:
        document = self._documents.get_document(workflow_id, plan_document_id)
        content = document.content
        if isinstance(content, StoryboardProductionPlanContentV3):
            return self._attach_v3_node(
                document,
                content,
                sequence_id=sequence_id,
                node_id=node_id,
                node_role="video_segment",
                agent_run_id=agent_run_id,
                idempotency_key=idempotency_key,
            )
        content = cast(StoryboardProductionPlanContentV2, content)
        existing = next(
            (
                item
                for item in content.node_records
                if item.sequence_id == sequence_id and item.node_role == "video_segment"
            ),
            None,
        )
        if existing is not None:
            if existing.node_id == node_id:
                return document
            raise _storyboard_error("Storyboard sequence already owns another Video Node.")
        return self._documents.apply_agent_patch(
            workflow_id,
            agent_run_id,
            AttachVideoNodePatchV2(
                operation="attach_video_node",
                document_id=document.document_id,
                expected_revision=document.revision,
                idempotency_key=idempotency_key,
                sequence_id=sequence_id,
                node_id=node_id,
            ),
        ).document

    def _attach_v3_node(
        self,
        document: AgentWorkingDocumentV2,
        content: StoryboardProductionPlanContentV3,
        *,
        sequence_id: str,
        node_id: str,
        node_role: Literal["storyboard_grid", "video_segment"],
        agent_run_id: str,
        idempotency_key: str,
    ) -> AgentWorkingDocumentV2:
        existing = next(
            (
                item
                for item in content.planned_nodes
                if item.sequence_id == sequence_id and item.node_role == node_role
            ),
            None,
        )
        if existing is not None:
            if existing.node_id == node_id:
                return document
            raise _storyboard_authority_error(
                f"Storyboard sequence already owns another {node_role} Node."
            )
        if self._workflows is None:
            raise V2PersistenceError(
                "storyboard_sequence_workflow_repository_required",
                "Storyboard planned Node attachment requires the workflow repository.",
                stage="storyboard_sequence_authoring",
            )
        node = self._workflows.get_node(document.workflow_id, node_id)
        planned = StoryboardPlannedNodeV3(
            sequence_id=sequence_id,
            node_role=node_role,
            node_id=node_id,
            node_revision=node.revision,
            materialization_id=(
                "materialization_"
                + sha256(
                    f"{document.document_id}:{sequence_id}:{node_role}:{node_id}".encode()
                ).hexdigest()[:32]
            ),
        )
        return self._documents.commit_content_mutation(
            workflow_id=document.workflow_id,
            agent_run_id=agent_run_id,
            document_id=document.document_id,
            expected_revision=document.revision,
            operation=f"attach_{node_role}_node",
            idempotency_key=idempotency_key,
            next_content=content.model_copy(
                update={"planned_nodes": content.planned_nodes + (planned,)}
            ),
        )

    def _append_event(
        self,
        *,
        workflow_id: str,
        document: AgentWorkingDocumentV2,
        agent_run_id: str,
        guidance_session_id: str,
        event_type: str,
        transition_key: str,
        payload: dict[str, object],
    ) -> None:
        if self._events is None:
            raise V2PersistenceError(
                "storyboard_sequence_event_repository_required",
                "Storyboard plan persistence requires the canonical event repository.",
                stage="storyboard_sequence_authoring",
            )
        self._events.append(
            V2EventInsert(
                workflow_id=workflow_id,
                event_type=event_type,
                transition_key=transition_key,
                created_at=document.updated_at.isoformat(),
                payload={
                    "agent_run_id": agent_run_id,
                    "guidance_session_id": guidance_session_id,
                    "plan_document_id": document.document_id,
                    "plan_revision": document.revision,
                    **payload,
                },
            )
        )

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
        registry = page.items[0].content
        anchors_by_alias = {
            anchor.alias: anchor for anchor in _available_anchor_projection(registry)
        }
        resolved = []
        for alias in aliases:
            anchor = anchors_by_alias.get(alias)
            if anchor is None or anchor.availability != "available" or anchor.source_id is None:
                raise _anchor_error(f"Storyboard anchor {alias} is not available for authoring.")
            resolved.append(anchor)
        return tuple(resolved)


class GuidedAnchorRegistryService:
    """Plan authoritative Anchor Registry mutations for an owning transaction."""

    _V3_ALIAS_PREFIX = {
        "world_setting": "WORLD",
        "product": "PRODUCT",
        "prop": "PROP",
        "character": "CHARACTER",
        "scene": "SCENE",
        "style": "STYLE",
        "composition": "COMPOSITION",
    }

    def __init__(
        self,
        *,
        workflows,
        documents: AgentWorkingDocumentService,
    ) -> None:
        self._workflows = workflows
        self._documents = documents

    def plan_planned_identity(
        self,
        *,
        workflow_id: str,
        document_id: str,
        expected_revision: int,
        agent_run_id: str,
        idempotency_key: str,
        identity_id: str,
        semantic_role: AgentAnchorSemanticRoleV3,
        display_name: str,
        summary: str,
        source: AgentAnchorSourceV3,
        acceptance_evidence: AnchorAcceptanceEvidenceV1,
    ) -> AgentDocumentMutationPlanV3:
        content = self._v3_content(workflow_id, document_id)
        if content.current_anchor(semantic_role) is not None:
            raise _anchor_authority_error(
                "agent_anchor_alias_conflict",
                "The semantic role already has a current accepted identity.",
            )
        alias = _next_v3_alias(self._V3_ALIAS_PREFIX[semantic_role], content)
        next_content = content.model_copy(
            update={
                "anchors": content.anchors
                + (
                    AgentAnchorV3(
                        alias=alias,
                        identity_id=identity_id,
                        semantic_role=semantic_role,
                        display_name=display_name,
                        summary=summary,
                        lifecycle="planned",
                        source=source,
                        acceptance_evidence=(acceptance_evidence,),
                    ),
                )
            }
        )
        return self._plan(
            workflow_id=workflow_id,
            document_id=document_id,
            expected_revision=expected_revision,
            agent_run_id=agent_run_id,
            idempotency_key=idempotency_key,
            operation="register_planned_anchor",
            content=next_content,
        )

    def plan_activate_identity(
        self,
        *,
        workflow_id: str,
        document_id: str,
        expected_revision: int,
        agent_run_id: str,
        idempotency_key: str,
        alias: str,
        source: AgentAnchorSourceV3,
        acceptance_evidence: AnchorAcceptanceEvidenceV1,
    ) -> AgentDocumentMutationPlanV3:
        content = self._v3_content(workflow_id, document_id)
        current = _require_v3_anchor(content, alias)
        if current.lifecycle != "planned":
            raise _anchor_authority_error(
                "agent_anchor_acceptance_stale",
                "Only a planned anchor can be activated.",
            )
        replacement = current.model_copy(
            update={
                "lifecycle": "active",
                "source": source,
                "acceptance_evidence": current.acceptance_evidence + (acceptance_evidence,),
            }
        )
        return self._plan_replacement(
            workflow_id=workflow_id,
            document_id=document_id,
            expected_revision=expected_revision,
            agent_run_id=agent_run_id,
            idempotency_key=idempotency_key,
            operation="activate_anchor",
            content=content,
            replacement=replacement,
        )

    def plan_replace_identity(
        self,
        *,
        workflow_id: str,
        document_id: str,
        expected_revision: int,
        agent_run_id: str,
        idempotency_key: str,
        identity_id: str,
        semantic_role: AgentAnchorSemanticRoleV3,
        display_name: str,
        summary: str,
        source: AgentAnchorSourceV3,
        acceptance_evidence: AnchorAcceptanceEvidenceV1,
    ) -> AgentDocumentMutationPlanV3:
        content = self._v3_content(workflow_id, document_id)
        current = content.current_anchor(semantic_role)
        if current is None:
            raise _anchor_authority_error(
                "agent_anchor_acceptance_stale",
                "The semantic role has no current identity to replace.",
            )
        retired = current.model_copy(update={"lifecycle": "retired"})
        alias = _next_v3_alias(self._V3_ALIAS_PREFIX[semantic_role], content)
        replacement = AgentAnchorV3(
            alias=alias,
            identity_id=identity_id,
            semantic_role=semantic_role,
            display_name=display_name,
            summary=summary,
            lifecycle="planned",
            source=source,
            acceptance_evidence=(acceptance_evidence,),
        )
        anchors = tuple(
            retired if anchor.alias == current.alias else anchor for anchor in content.anchors
        ) + (replacement,)
        return self._plan(
            workflow_id=workflow_id,
            document_id=document_id,
            expected_revision=expected_revision,
            agent_run_id=agent_run_id,
            idempotency_key=idempotency_key,
            operation="replace_anchor",
            content=content.model_copy(update={"anchors": anchors}),
        )

    def plan_invalidate_identity(
        self,
        *,
        workflow_id: str,
        document_id: str,
        expected_revision: int,
        agent_run_id: str,
        idempotency_key: str,
        alias: str,
        acceptance_evidence: AnchorAcceptanceEvidenceV1,
    ) -> AgentDocumentMutationPlanV3:
        content = self._v3_content(workflow_id, document_id)
        current = _require_v3_anchor(content, alias)
        replacement = current.model_copy(
            update={
                "lifecycle": "invalid",
                "acceptance_evidence": current.acceptance_evidence + (acceptance_evidence,),
            }
        )
        return self._plan_replacement(
            workflow_id=workflow_id,
            document_id=document_id,
            expected_revision=expected_revision,
            agent_run_id=agent_run_id,
            idempotency_key=idempotency_key,
            operation="invalidate_anchor",
            content=content,
            replacement=replacement,
        )

    def _v3_content(self, workflow_id: str, document_id: str) -> AnchorRegistryContentV3:
        document = self._documents.get_document(workflow_id, document_id)
        if document.kind != "anchor_registry" or not isinstance(
            document.content, AnchorRegistryContentV3
        ):
            raise _anchor_authority_error(
                "agent_anchor_role_invalid",
                "Authoritative anchor planning requires an Anchor Registry V3 document.",
            )
        return document.content

    def _plan_replacement(
        self,
        *,
        workflow_id: str,
        document_id: str,
        expected_revision: int,
        agent_run_id: str,
        idempotency_key: str,
        operation: str,
        content: AnchorRegistryContentV3,
        replacement: AgentAnchorV3,
    ) -> AgentDocumentMutationPlanV3:
        anchors = tuple(
            replacement if anchor.alias == replacement.alias else anchor
            for anchor in content.anchors
        )
        return self._plan(
            workflow_id=workflow_id,
            document_id=document_id,
            expected_revision=expected_revision,
            agent_run_id=agent_run_id,
            idempotency_key=idempotency_key,
            operation=operation,
            content=content.model_copy(update={"anchors": anchors}),
        )

    def _plan(
        self,
        *,
        workflow_id: str,
        document_id: str,
        expected_revision: int,
        agent_run_id: str,
        idempotency_key: str,
        operation: str,
        content: AnchorRegistryContentV3,
    ) -> AgentDocumentMutationPlanV3:
        return self._documents.plan_content_mutation(
            workflow_id=workflow_id,
            agent_run_id=agent_run_id,
            document_id=document_id,
            expected_revision=expected_revision,
            operation=operation,
            idempotency_key=idempotency_key,
            next_content=content,
        )


def _storyboard_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_sequence_invalid",
        message,
        stage="storyboard_sequence_authoring",
    )


def _storyboard_authority_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "agent_storyboard_plan_invalid",
        message,
        stage="storyboard_sequence_authoring",
    )


def _normalize_storyboard_text(value: str) -> str:
    """Normalize only whitespace and case for exact structural comparisons."""

    return " ".join(value.split()).casefold()


def _previous_sequence(
    content: StoryboardProductionPlanContentV3,
    sequence: StoryboardNarrativeSegmentV2,
) -> StoryboardNarrativeSegmentV2 | None:
    return next(
        (item for item in content.segments if item.order == sequence.order - 1),
        None,
    )


def _continuity_handoff(
    content: StoryboardProductionPlanContentV3,
    sequence: StoryboardNarrativeSegmentV2,
) -> str:
    previous = _previous_sequence(content, sequence)
    if previous is None:
        return ""
    previous_rows = tuple(row for row in content.rows if row.sequence_id == previous.sequence_id)
    if len(previous_rows) != 9:
        raise _storyboard_authority_error(
            "A later Storyboard sequence requires the previous sequence's final panel."
        )
    handoff = (
        f"Previous sequence {previous.sequence_id} closing state: {previous.end_state}. "
        f"Final panel beat: {previous_rows[-1].content_beat}."
    )
    if len(handoff) > 2_048:
        raise _storyboard_authority_error(
            "The Storyboard continuity handoff exceeds its bounded size."
        )
    return handoff


def _sequence_local_generation_prompt(
    content: StoryboardProductionPlanContentV3,
    sequence_id: str,
    generation_prompt: str,
    *,
    rows: tuple[StoryboardSequenceRowDraftV2, ...],
) -> str:
    """Keep the persisted prompt local and append only the bounded prior handoff."""

    normalized_prompt = _normalize_storyboard_text(generation_prompt)
    for sibling in content.segments:
        if sibling.sequence_id == sequence_id:
            continue
        sibling_values = [sibling.narrative_goal]
        sibling_values.extend(
            row.content_beat for row in content.rows if row.sequence_id == sibling.sequence_id
        )
        if any(_normalize_storyboard_text(value) in normalized_prompt for value in sibling_values):
            raise _storyboard_authority_error(
                "Storyboard sequence prompt contains a sibling sequence beat."
            )
    sequence = next(item for item in content.segments if item.sequence_id == sequence_id)
    handoff = _continuity_handoff(content, sequence)
    row_projection = " ".join(
        f"Panel {row.panel_index}: {row.content_beat}; camera: {row.camera_description}."
        for row in rows
    )
    parts = [generation_prompt.rstrip(), f"Current sequence rows: {row_projection}"]
    if handoff:
        parts.append(handoff)
    return "\n\n".join(parts)


def _prompt_without_continuity_handoff(prompt: str) -> str:
    for marker in ("\n\nCurrent sequence rows:", "\n\nPrevious sequence "):
        prompt = prompt.split(marker, 1)[0]
    return prompt


def _ensure_adjacent_sequence_is_distinct(
    content: StoryboardProductionPlanContentV3,
    sequence: StoryboardNarrativeSegmentV2,
    draft: StoryboardSegmentMaterializationDraftV2,
) -> None:
    previous = _previous_sequence(content, sequence)
    if previous is None:
        return
    previous_rows = tuple(row for row in content.rows if row.sequence_id == previous.sequence_id)
    previous_materialization = next(
        item
        for item in content.segment_materializations
        if item.sequence_id == previous.sequence_id
    )
    if len(previous_rows) != 9 or previous_materialization.status != "materialized":
        return
    previous_payload = (
        _normalize_storyboard_text(previous.narrative_goal),
        tuple(
            (
                row.panel_index,
                _normalize_storyboard_text(row.content_beat),
                _normalize_storyboard_text(row.camera_description),
            )
            for row in previous_rows
        ),
        _normalize_storyboard_text(
            _prompt_without_continuity_handoff(previous_materialization.generation_prompt or "")
        ),
    )
    current_payload = (
        _normalize_storyboard_text(sequence.narrative_goal),
        tuple(
            (
                row.panel_index,
                _normalize_storyboard_text(row.content_beat),
                _normalize_storyboard_text(row.camera_description),
            )
            for row in draft.rows
        ),
        _normalize_storyboard_text(_prompt_without_continuity_handoff(draft.generation_prompt)),
    )
    if current_payload == previous_payload:
        raise _storyboard_authority_error(
            "Adjacent Storyboard sequences contain exact duplicate narrative content."
        )


def _anchor_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_anchor_resolution_failed",
        message,
        stage="storyboard_sequence_authoring",
    )


def _next_v3_alias(prefix: str, content: AnchorRegistryContentV3) -> str:
    aliases = {anchor.alias for anchor in content.anchors}
    for index in range(1, 100):
        candidate = f"{prefix}{index:02d}"
        if candidate not in aliases:
            return candidate
    raise _anchor_authority_error(
        "agent_anchor_alias_conflict",
        "The Anchor Registry alias range is exhausted.",
    )


def _require_v3_anchor(content: AnchorRegistryContentV3, alias: str) -> AgentAnchorV3:
    anchor = next((item for item in content.anchors if item.alias == alias), None)
    if anchor is None:
        raise _anchor_authority_error(
            "agent_anchor_acceptance_stale",
            "The Anchor Registry alias was not found.",
        )
    return anchor


def _anchor_authority_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_anchor_registry")


def _available_anchor_projection(
    content: AnchorRegistryContentV2 | AnchorRegistryContentV3,
) -> tuple[AgentAnchorV2, ...]:
    if isinstance(content, AnchorRegistryContentV2):
        return tuple(
            item
            for item in content.anchors
            if item.availability == "available" and item.source_id is not None
        )
    anchor_type_by_role = {
        "world_setting": "world_setting",
        "product": "subject",
        "prop": "subject",
        "character": "subject",
        "scene": "environment",
        "style": "style",
        "composition": "composition",
    }
    projected: list[AgentAnchorV2] = []
    for anchor in content.anchors:
        if anchor.lifecycle != "active":
            continue
        source = anchor.source
        if source.source_kind == "node":
            source_kind = "node"
            source_id = source.node_id
        elif source.source_kind == "image_asset_version":
            source_kind = "image_asset"
            source_id = source.asset_id
        else:
            source_kind = "skill_snapshot"
            source_id = source.skill_id
        projected.append(
            AgentAnchorV2(
                alias=anchor.alias,
                anchor_type=anchor_type_by_role[anchor.semantic_role],
                display_name=anchor.display_name,
                summary=anchor.summary,
                source_kind=source_kind,
                source_id=source_id,
                availability="available",
            )
        )
    return tuple(projected)
