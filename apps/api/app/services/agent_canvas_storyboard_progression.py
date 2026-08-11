"""Advance progressive storyboard Drafts after the first grid becomes Ready."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from typing import cast

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    CanvasPositionV2,
)
from app.schemas.agent_canvas_ad_media import (
    StoryboardGridContentV2,
    StoryboardPanelV2,
    VideoSegmentContentV2,
)
from app.schemas.agent_working_documents import StoryboardProductionPlanContentV2
from app.services.agent_canvas_conversation import VideoAgentGateway
from app.services.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthoringService,
)


BindingCapabilityValidator = Callable[[object, frozenset[str], int], object]


class ProgressiveStoryboardReadyService:
    """Freeze Grid 1 and atomically publish sequence-local sibling Drafts."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        authoring: StoryboardSequenceAuthoringService,
        gateway: VideoAgentGateway,
        binding_capability_validator: BindingCapabilityValidator | None = None,
    ) -> None:
        self._workflows = workflows
        self._authoring = authoring
        self._gateway = gateway
        self._binding_capability_validator = binding_capability_validator

    def on_node_ready(self, node: CanvasNodeV2) -> tuple[str, ...]:
        if (
            node.node_type != "image"
            or node.creative_role != "storyboard_sequence"
            or node.status != "ready"
            or node.output_asset_id is None
        ):
            return ()
        page = self._authoring.list_plans(node.workflow_id)
        plan = next(
            (
                item
                for item in page.items
                if any(
                    record.node_role == "storyboard_grid"
                    and record.sequence_id
                    == cast(StoryboardProductionPlanContentV2, item.content).segments[0].sequence_id
                    and record.node_id == node.node_id
                    for record in cast(StoryboardProductionPlanContentV2, item.content).node_records
                )
            ),
            None,
        )
        if plan is None:
            source_document_id = node.metadata.get("source_agent_document_id")
            plan = next(
                (item for item in page.items if item.document_id == source_document_id),
                None,
            )
            if plan is None:
                return ()
            content = cast(StoryboardProductionPlanContentV2, plan.content)
            if content.visual_anchor is None or content.visual_anchor.node_id == node.node_id:
                return ()
            return self._materialize_sibling_branch(plan.document_id, content, node)
        plan = self._authoring.freeze_visual_anchor(
            workflow_id=node.workflow_id,
            plan_document_id=plan.document_id,
            grid_node_id=node.node_id,
            agent_run_id=f"storyboard-ready:{node.node_id}:{node.revision}",
            idempotency_key=f"storyboard-anchor:{node.node_id}:{node.output_asset_id}",
        )
        created: list[str] = []
        content = cast(StoryboardProductionPlanContentV2, plan.content)
        first_sequence = content.segments[0]
        created.extend(
            self._ensure_video(
                plan.document_id,
                first_sequence.sequence_id,
                node,
                duration_seconds=first_sequence.end_seconds - first_sequence.start_seconds,
            )
        )
        for sequence in content.segments[1:]:
            grid_id = _node_id(plan.document_id, sequence.sequence_id, "grid")
            workflow = self._workflows.get_workflow(node.workflow_id)
            existing = {item.node_id: item for item in workflow.nodes}.get(grid_id)
            if existing is None:
                segment_context = self._authoring.build_segment_context(
                    node.workflow_id,
                    plan.document_id,
                    sequence.sequence_id,
                    style_excerpt=_style_excerpt(node),
                )
                segment = self._gateway.materialize_storyboard_segment(
                    segment_context,
                    request_identity=f"{plan.document_id}:{sequence.sequence_id}",
                )
                plan = self._authoring.persist_segment(
                    workflow_id=node.workflow_id,
                    plan_document_id=plan.document_id,
                    sequence_id=sequence.sequence_id,
                    agent_run_id=f"storyboard-segment:{sequence.sequence_id}",
                    idempotency_key=f"storyboard-segment:{plan.document_id}:{sequence.sequence_id}",
                    draft=segment,
                )
                grid = _grid_node(
                    workflow_id=node.workflow_id,
                    node_id=grid_id,
                    order=sequence.order,
                    sequence=sequence,
                    segment=segment,
                    source=node,
                )
                bindings = _later_grid_bindings(
                    workflow=workflow,
                    grid_one=node,
                    target=grid,
                )
                self._validate_grid_capacity(grid, bindings)
                self._workflows.add_node_with_bindings(
                    grid,
                    bindings,
                    expected_revision=workflow.revision,
                )
                created.append(grid.node_id)
                plan = self._authoring.attach_grid_node(
                    workflow_id=node.workflow_id,
                    plan_document_id=plan.document_id,
                    sequence_id=sequence.sequence_id,
                    node_id=grid.node_id,
                    agent_run_id=f"storyboard-grid:{sequence.sequence_id}",
                    idempotency_key=f"storyboard-grid:{plan.document_id}:{sequence.sequence_id}",
                )
                existing = grid
            created.extend(
                self._ensure_video(
                    plan.document_id,
                    sequence.sequence_id,
                    existing,
                    duration_seconds=sequence.end_seconds - sequence.start_seconds,
                )
            )
        return tuple(created)

    def _materialize_sibling_branch(
        self,
        plan_document_id: str,
        content: StoryboardProductionPlanContentV2,
        grid_one: CanvasNodeV2,
    ) -> tuple[str, ...]:
        branch_scope = f"{plan_document_id}:{grid_one.node_id}"
        created: list[str] = []
        first_sequence = content.segments[0]
        created.extend(
            self._ensure_video(
                plan_document_id,
                first_sequence.sequence_id,
                grid_one,
                duration_seconds=(first_sequence.end_seconds - first_sequence.start_seconds),
                node_identity_scope=branch_scope,
                attach_to_plan=False,
            )
        )
        for sequence in content.segments[1:]:
            grid_id = _node_id(branch_scope, sequence.sequence_id, "grid")
            workflow = self._workflows.get_workflow(grid_one.workflow_id)
            grid = {item.node_id: item for item in workflow.nodes}.get(grid_id)
            if grid is None:
                segment_context = self._authoring.build_segment_context(
                    grid_one.workflow_id,
                    plan_document_id,
                    sequence.sequence_id,
                    style_excerpt=_style_excerpt(grid_one),
                )
                segment = self._gateway.materialize_storyboard_segment(
                    segment_context,
                    request_identity=f"{branch_scope}:{sequence.sequence_id}",
                )
                grid = _grid_node(
                    workflow_id=grid_one.workflow_id,
                    node_id=grid_id,
                    order=sequence.order,
                    sequence=sequence,
                    segment=segment,
                    source=grid_one,
                )
                bindings = _later_grid_bindings(
                    workflow=workflow,
                    grid_one=grid_one,
                    target=grid,
                )
                self._validate_grid_capacity(grid, bindings)
                self._workflows.add_node_with_bindings(
                    grid,
                    bindings,
                    expected_revision=workflow.revision,
                )
                created.append(grid.node_id)
            created.extend(
                self._ensure_video(
                    plan_document_id,
                    sequence.sequence_id,
                    grid,
                    duration_seconds=sequence.end_seconds - sequence.start_seconds,
                    node_identity_scope=branch_scope,
                    attach_to_plan=False,
                )
            )
        return tuple(created)

    def _validate_grid_capacity(
        self,
        node: CanvasNodeV2,
        bindings: tuple[CanvasBindingV2, ...],
    ) -> None:
        if self._binding_capability_validator is None:
            return
        references = tuple(
            binding
            for binding in bindings
            if binding.input_role in {"image_reference", "video_reference", "audio_reference"}
        )
        decision = self._binding_capability_validator(
            node,
            frozenset(binding.input_role.removesuffix("_reference") for binding in references),
            len(references),
        )
        if not getattr(decision, "accepted", False):
            raise V2PersistenceError(
                "guided_reference_model_incompatible",
                "The selected model cannot consume the required Grid 1 visual anchor.",
                stage="storyboard_sequence_authoring",
            )

    def _ensure_video(
        self,
        plan_document_id: str,
        sequence_id: str,
        grid: CanvasNodeV2,
        *,
        duration_seconds: float,
        node_identity_scope: str | None = None,
        attach_to_plan: bool = True,
    ) -> tuple[str, ...]:
        video_id = _node_id(
            node_identity_scope or plan_document_id,
            sequence_id,
            "video",
        )
        workflow = self._workflows.get_workflow(grid.workflow_id)
        if any(item.node_id == video_id for item in workflow.nodes):
            return ()
        content = StoryboardGridContentV2.model_validate(grid.structured_content)
        now = datetime.now(timezone.utc)
        video = CanvasNodeV2(
            node_id=video_id,
            workflow_id=grid.workflow_id,
            node_type="video",
            creative_role="storyboard_video",
            title=f"Video {sequence_id}",
            status="draft",
            summary_prompt=content.narrative_goal,
            generation_prompt=(
                "Use the complete matching storyboard grid as the primary ordered reference. "
                "Lock the opening frame to panel 1 without requiring a cropped panel asset, "
                "then follow panels 1 through 9 as one continuous commercial segment. "
                "Preserve required dialogue, voice performance, native ambience, movement, "
                "and synchronized action effects. Generate no background music."
            ),
            structured_content=VideoSegmentContentV2(
                segment_summary=content.sequence_summary,
                duration_seconds=duration_seconds,
                storyboard_content="Follow the nine ordered storyboard frames.",
                environment_sound="Preserve scene ambience.",
                action_effects="Preserve declared action sounds.",
                background_music=False,
            ).model_dump(mode="json"),
            position=CanvasPositionV2(x=grid.position.x + 360, y=grid.position.y),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        element_bindings = tuple(
            binding
            for binding in workflow.bindings
            if binding.target_node_id == grid.node_id
            and binding.metadata.get("storyboard_reference_purpose") != "sequence_visual_anchor"
        )
        bindings = (
            CanvasBindingV2(
                binding_id=_binding_id(video_id, "grid", 0),
                workflow_id=grid.workflow_id,
                source=CanvasBindingSourceNodeV2(source_node_id=grid.node_id),
                target_node_id=video.node_id,
                input_role="image_reference",
                required=True,
                order=0,
                metadata={"semantic_reference_role": "storyboard_visual_reference"},
                created_at=now,
                updated_at=now,
            ),
            *tuple(
                binding.model_copy(
                    update={
                        "binding_id": _binding_id(video_id, "element", index),
                        "target_node_id": video.node_id,
                        "order": index,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                for index, binding in enumerate(element_bindings, start=1)
            ),
        )
        self._workflows.add_node_with_bindings(
            video,
            bindings,
            expected_revision=workflow.revision,
        )
        if attach_to_plan:
            self._authoring.attach_video_node(
                workflow_id=grid.workflow_id,
                plan_document_id=plan_document_id,
                sequence_id=sequence_id,
                node_id=video.node_id,
                agent_run_id=f"storyboard-video:{sequence_id}",
                idempotency_key=f"storyboard-video:{plan_document_id}:{sequence_id}",
            )
        return (video.node_id,)


def _later_grid_bindings(
    *,
    workflow,
    grid_one: CanvasNodeV2,
    target: CanvasNodeV2,
) -> tuple[CanvasBindingV2, ...]:
    now = target.created_at
    copied = tuple(
        binding for binding in workflow.bindings if binding.target_node_id == grid_one.node_id
    )
    bindings = [
        binding.model_copy(
            update={
                "binding_id": _binding_id(target.node_id, "element", index),
                "target_node_id": target.node_id,
                "order": index,
                "created_at": now,
                "updated_at": now,
            }
        )
        for index, binding in enumerate(copied)
    ]
    bindings.append(
        CanvasBindingV2(
            binding_id=_binding_id(target.node_id, "anchor", len(bindings)),
            workflow_id=target.workflow_id,
            source=CanvasBindingSourceNodeV2(source_node_id=grid_one.node_id),
            target_node_id=target.node_id,
            input_role="image_reference",
            required=True,
            order=len(bindings),
            metadata={
                "semantic_reference_role": "style_composition_reference",
                "storyboard_reference_purpose": "sequence_visual_anchor",
            },
            created_at=now,
            updated_at=now,
        )
    )
    return tuple(bindings)


def _grid_node(
    *,
    workflow_id: str,
    node_id: str,
    order: int,
    sequence,
    segment,
    source: CanvasNodeV2,
) -> CanvasNodeV2:
    now = datetime.now(timezone.utc)
    source_content = StoryboardGridContentV2.model_validate(source.structured_content)
    return CanvasNodeV2(
        node_id=node_id,
        workflow_id=workflow_id,
        node_type="image",
        creative_role="storyboard_sequence",
        title=f"Storyboard Grid {order}",
        status="draft",
        summary_prompt=sequence.narrative_goal,
        generation_prompt=segment.generation_prompt,
        structured_content=StoryboardGridContentV2(
            sequence_summary=sequence.narrative_goal,
            narrative_goal=sequence.narrative_goal,
            style=source_content.style,
            panels=tuple(
                StoryboardPanelV2(
                    panel_index=row.panel_index,
                    beat=row.content_beat,
                    composition=row.camera_description,
                    camera=row.camera_description,
                    subject_action=row.content_beat,
                    continuity_from_previous=(
                        sequence.start_state
                        if row.panel_index == 1
                        else "Continue the prior panel action."
                    ),
                )
                for row in segment.rows
            ),
        ).model_dump(mode="json"),
        position=CanvasPositionV2(x=source.position.x, y=source.position.y + (order - 1) * 280),
        revision=1,
        created_at=now,
        updated_at=now,
    )


def _style_excerpt(node: CanvasNodeV2) -> str:
    style = node.structured_content.get("style")
    return str(style)[:8_192] if style is not None else ""


def _node_id(document_id: str, sequence_id: str, role: str) -> str:
    return f"node_{sha256(f'{document_id}:{sequence_id}:{role}'.encode()).hexdigest()[:32]}"


def _binding_id(node_id: str, role: str, index: int) -> str:
    return f"binding_{sha256(f'{node_id}:{role}:{index}'.encode()).hexdigest()[:32]}"
