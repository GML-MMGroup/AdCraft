"""Advance progressive storyboard Drafts after the first grid becomes Ready."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_production_closure_repository import (
    AgentCanvasProductionClosureRepository,
)
from app.persistence.event_repository import EventRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    CanvasPositionV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas_ad_media import (
    StoryboardGridContentV2,
    StoryboardPanelV2,
    VideoSegmentContentV2,
)
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardSegmentMaterializationDraftV2,
    StoryboardSequenceRowDraftV2,
)
from app.schemas.agent_canvas_production_closure import (
    GuidedMediaConfirmationV1,
    StoryboardFanoutBindingPlanV1,
    StoryboardFanoutNodePlanV1,
    StoryboardFanoutPlanV1,
)
from app.schemas.agent_working_documents import (
    StoryboardProductionPlanContentV2,
    StoryboardProductionPlanContentV3,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_conversation import VideoAgentGateway
from app.services.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthoringService,
)
from app.services.agent_canvas_world_setting import WorldSettingBindingPolicy


BindingCapabilityValidator = Callable[[object, frozenset[str], int], object]
StoryboardPipelinePreparedCallback = Callable[[str, str], object]


class ProgressiveStoryboardReadyService:
    """Freeze Grid 1 and atomically publish sequence-local sibling Drafts."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        authoring: StoryboardSequenceAuthoringService,
        gateway: VideoAgentGateway,
        receipts: AgentCanvasProductionClosureRepository | None = None,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        events: EventRepository | None = None,
        binding_capability_validator: BindingCapabilityValidator | None = None,
        on_storyboard_pipeline_prepared: StoryboardPipelinePreparedCallback | None = None,
    ) -> None:
        self._workflows = workflows
        self._authoring = authoring
        self._gateway = gateway
        self._receipts = receipts
        self._asset_resolver = asset_resolver
        self._events = events
        self._binding_capability_validator = binding_capability_validator
        self._on_storyboard_pipeline_prepared = on_storyboard_pipeline_prepared

    def on_node_ready(
        self,
        node: CanvasNodeV2,
        *,
        confirmation: GuidedMediaConfirmationV1 | None = None,
    ) -> tuple[str, ...]:
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
                    and record.sequence_id == item.content.segments[0].sequence_id
                    and record.node_id == node.node_id
                    for record in _planned_nodes(item.content)
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
            content = _plan_content(plan.content)
            if content.visual_anchor is None or content.visual_anchor.node_id == node.node_id:
                return ()
            return self._materialize_sibling_branch(plan.document_id, content, node)
        replay: StoryboardFanoutPlanV1 | None = None
        if self._receipts is not None:
            if confirmation is None or self._asset_resolver is None:
                raise V2PersistenceError(
                    "guided_media_confirmation_required",
                    "Grid 1 requires exact media confirmation before Storyboard fan-out.",
                    stage="storyboard_progression",
                )
            asset = self._asset_resolver(node.output_asset_id)
            fanout_plan_id = _fanout_plan_id(confirmation)
            try:
                replay = self._receipts.get_fanout(fanout_plan_id)
            except V2PersistenceError as error:
                if error.code != "guided_production_receipt_not_found":
                    raise
            else:
                if (
                    replay.visual_anchor_confirmation_id != confirmation.confirmation_id
                    or replay.plan_document_id != plan.document_id
                    or replay.plan_revision > plan.revision
                    or replay.visual_anchor_node_id != node.node_id
                    or replay.visual_anchor_node_revision != node.revision
                    or replay.visual_anchor_asset_id != asset.asset_id
                    or replay.visual_anchor_asset_version_id != asset.version_id
                    or replay.visual_anchor_asset_digest != asset.checksum
                ):
                    raise V2PersistenceError(
                        "guided_media_confirmation_stale",
                        "Stored Storyboard fan-out authority does not match current evidence.",
                        stage="storyboard_progression",
                    )
                content = _plan_content(plan.content)
                if content.visual_anchor is None or content.visual_anchor.node_id != node.node_id:
                    raise V2PersistenceError(
                        "guided_media_confirmation_stale",
                        "Stored Storyboard fan-out authority does not match the current Plan anchor.",
                        stage="storyboard_progression",
                    )
            if replay is None:
                self._validate_confirmation(plan, node, asset, confirmation)
        if replay is None:
            plan = self._authoring.freeze_visual_anchor(
                workflow_id=node.workflow_id,
                plan_document_id=plan.document_id,
                grid_node_id=node.node_id,
                agent_run_id=f"storyboard-ready:{node.node_id}:{node.revision}",
                idempotency_key=f"storyboard-anchor:{node.node_id}:{node.output_asset_id}",
                asset_version_id=(asset.version_id if self._receipts is not None else None),
                acceptance_evidence_id=(
                    confirmation.confirmation_id if confirmation is not None else None
                ),
            )
        created: list[str] = []
        content = _plan_content(plan.content)
        fanout_authority = replay
        if self._receipts is not None and replay is None:
            fanout_authority = self._receipts.save_fanout(
                _fanout_plan(
                    plan_document_id=plan.document_id,
                    plan_revision=plan.revision,
                    workflow=self._workflows.get_workflow(node.workflow_id),
                    content=content,
                    grid_one=node,
                    asset=asset,
                    confirmation=confirmation,
                )
            )
        first_sequence = content.segments[0]
        created.extend(
            self._ensure_video(
                plan.document_id,
                first_sequence.sequence_id,
                node,
                duration_seconds=first_sequence.end_seconds - first_sequence.start_seconds,
                aspect_ratio=content.global_parameters.aspect_ratio,
            )
        )
        for sequence in content.segments[1:]:
            grid_id = _node_id(plan.document_id, sequence.sequence_id, "grid")
            workflow = self._workflows.get_workflow(node.workflow_id)
            existing = {item.node_id: item for item in workflow.nodes}.get(grid_id)
            if existing is None:
                segment = _accepted_segment(
                    content,
                    sequence.sequence_id,
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
                    aspect_ratio=content.global_parameters.aspect_ratio,
                )
            )
        if created and self._on_storyboard_pipeline_prepared is not None:
            self._on_storyboard_pipeline_prepared(node.workflow_id, plan.document_id)
        if self._events is not None and fanout_authority is not None:
            event_time = datetime.now(timezone.utc).isoformat()
            self._events.append(
                V2EventInsert(
                    workflow_id=node.workflow_id,
                    node_id=node.node_id,
                    event_type="storyboard_visual_anchor_confirmed",
                    transition_key=(
                        "storyboard-visual-anchor-confirmed:"
                        f"{fanout_authority.visual_anchor_confirmation_id}"
                    ),
                    created_at=event_time,
                    payload={
                        "fanout_plan_id": fanout_authority.fanout_plan_id,
                        "confirmation_id": fanout_authority.visual_anchor_confirmation_id,
                        "node_revision": fanout_authority.visual_anchor_node_revision,
                        "asset_id": fanout_authority.visual_anchor_asset_id,
                        "asset_version_id": fanout_authority.visual_anchor_asset_version_id,
                        "plan_document_id": fanout_authority.plan_document_id,
                        "plan_revision": fanout_authority.plan_revision,
                    },
                )
            )
            self._events.append(
                V2EventInsert(
                    workflow_id=node.workflow_id,
                    node_id=node.node_id,
                    event_type="storyboard_fanout_committed",
                    transition_key=f"storyboard-fanout-committed:{fanout_authority.fanout_plan_id}",
                    created_at=event_time,
                    payload={
                        "fanout_plan_id": fanout_authority.fanout_plan_id,
                        "plan_document_id": fanout_authority.plan_document_id,
                        "plan_revision": fanout_authority.plan_revision,
                        "planned_node_ids": [item.node_id for item in fanout_authority.nodes],
                        "planned_binding_ids": [
                            item.binding_id for item in fanout_authority.bindings
                        ],
                    },
                )
            )
        return tuple(created)

    @staticmethod
    def _validate_confirmation(
        plan,
        node: CanvasNodeV2,
        asset: ProjectAssetSummaryV2,
        confirmation: GuidedMediaConfirmationV1,
    ) -> None:
        expected = (
            confirmation.workflow_id == node.workflow_id
            and confirmation.plan_document_id == plan.document_id
            and confirmation.plan_revision == plan.revision
            and confirmation.media_role == "image"
            and confirmation.sequence_id == plan.content.segments[0].sequence_id
            and confirmation.node_id == node.node_id
            and confirmation.node_revision == node.revision
            and confirmation.asset_id == node.output_asset_id == asset.asset_id
            and confirmation.asset_version_id == asset.version_id
            and confirmation.asset_digest == asset.checksum
            and asset.status == "ready"
            and asset.media_type == "image"
        )
        if not expected:
            raise V2PersistenceError(
                "guided_media_confirmation_stale",
                "Grid 1 media confirmation does not match current Plan and Asset authority.",
                stage="storyboard_progression",
                details={"confirmation_id": confirmation.confirmation_id},
            )

    def _materialize_sibling_branch(
        self,
        plan_document_id: str,
        content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
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
                aspect_ratio=content.global_parameters.aspect_ratio,
                node_identity_scope=branch_scope,
                attach_to_plan=False,
            )
        )
        for sequence in content.segments[1:]:
            grid_id = _node_id(branch_scope, sequence.sequence_id, "grid")
            workflow = self._workflows.get_workflow(grid_one.workflow_id)
            grid = {item.node_id: item for item in workflow.nodes}.get(grid_id)
            if grid is None:
                segment = _accepted_segment(
                    content,
                    sequence.sequence_id,
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
                    aspect_ratio=content.global_parameters.aspect_ratio,
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
        aspect_ratio: str,
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
            parameters={
                "duration_seconds": duration_seconds,
                "aspect_ratio": aspect_ratio,
            },
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
                        "metadata": _retarget_binding_metadata(
                            binding,
                            target_role=video.creative_role,
                        ),
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


def _accepted_segment(
    content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
    sequence_id: str,
) -> StoryboardSegmentMaterializationDraftV2:
    rows = tuple(row for row in content.rows if row.sequence_id == sequence_id)
    if len(rows) != 9:
        raise V2PersistenceError(
            "storyboard_fanout_invalid",
            "Storyboard fan-out requires nine accepted Plan rows for every sequence.",
            stage="storyboard_progression",
            details={"sequence_id": sequence_id, "row_count": len(rows)},
        )
    generation_prompt = next(
        (
            item.generation_prompt
            for item in getattr(content, "segment_materializations", ())
            if item.sequence_id == sequence_id and item.generation_prompt
        ),
        None,
    )
    if generation_prompt is None:
        sequence = next(item for item in content.segments if item.sequence_id == sequence_id)
        generation_prompt = (
            "Render one text-free 3x3 storyboard grid from the accepted Plan rows. "
            f"Narrative goal: {sequence.narrative_goal}"
        )
    return StoryboardSegmentMaterializationDraftV2(
        rows=tuple(
            StoryboardSequenceRowDraftV2(
                panel_index=row.panel_index,
                content_beat=row.content_beat,
                anchor_aliases=row.anchor_aliases,
                camera_description=row.camera_description,
            )
            for row in rows
        ),
        generation_prompt=generation_prompt,
    )


def _plan_content(
    content: object,
) -> StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3:
    if isinstance(content, (StoryboardProductionPlanContentV2, StoryboardProductionPlanContentV3)):
        return content
    raise V2PersistenceError(
        "storyboard_fanout_invalid",
        "Storyboard fan-out requires a canonical Production Plan.",
        stage="storyboard_progression",
    )


def _planned_nodes(
    content: object,
) -> tuple[object, ...]:
    canonical = _plan_content(content)
    if isinstance(canonical, StoryboardProductionPlanContentV3):
        return canonical.planned_nodes
    return canonical.node_records


def _fanout_plan(
    *,
    plan_document_id: str,
    plan_revision: int,
    workflow,
    content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
    grid_one: CanvasNodeV2,
    asset: ProjectAssetSummaryV2,
    confirmation: GuidedMediaConfirmationV1,
) -> StoryboardFanoutPlanV1:
    if asset.version_id is None:
        raise V2PersistenceError(
            "guided_media_confirmation_stale",
            "Grid 1 Asset version is required for Storyboard fan-out.",
            stage="storyboard_progression",
        )
    node_plans: list[StoryboardFanoutNodePlanV1] = []
    binding_plans: list[StoryboardFanoutBindingPlanV1] = []
    preparation_keys: list[str] = []
    grid_one_input_count = sum(
        1 for binding in workflow.bindings if binding.target_node_id == grid_one.node_id
    )
    for sequence in content.segments:
        grid_id = (
            grid_one.node_id
            if sequence.order == 1
            else _node_id(plan_document_id, sequence.sequence_id, "grid")
        )
        if sequence.order > 1:
            node_plans.append(
                StoryboardFanoutNodePlanV1(
                    sequence_id=sequence.sequence_id,
                    order=sequence.order,
                    node_role="storyboard_grid",
                    node_id=grid_id,
                )
            )
            binding_plans.append(
                StoryboardFanoutBindingPlanV1(
                    binding_id=_binding_id(grid_id, "anchor", grid_one_input_count),
                    source_node_id=grid_one.node_id,
                    target_node_id=grid_id,
                    input_role="image_reference",
                    required=True,
                    order=grid_one_input_count,
                    storyboard_reference_purpose="sequence_visual_anchor",
                )
            )
            preparation_keys.append(f"prepare:{grid_id}")
        video_id = _node_id(plan_document_id, sequence.sequence_id, "video")
        node_plans.append(
            StoryboardFanoutNodePlanV1(
                sequence_id=sequence.sequence_id,
                order=sequence.order,
                node_role="video_segment",
                node_id=video_id,
            )
        )
        binding_plans.append(
            StoryboardFanoutBindingPlanV1(
                binding_id=_binding_id(video_id, "grid", 0),
                source_node_id=grid_id,
                target_node_id=video_id,
                input_role="image_reference",
                required=True,
                order=0,
            )
        )
        preparation_keys.append(f"prepare:{video_id}")
    return StoryboardFanoutPlanV1(
        fanout_plan_id=_fanout_plan_id(confirmation),
        logical_identity=confirmation.logical_identity,
        workflow_id=grid_one.workflow_id,
        plan_document_id=plan_document_id,
        plan_revision=plan_revision,
        visual_anchor_node_id=grid_one.node_id,
        visual_anchor_node_revision=grid_one.revision,
        visual_anchor_asset_id=asset.asset_id,
        visual_anchor_asset_version_id=asset.version_id,
        visual_anchor_asset_digest=asset.checksum,
        visual_anchor_confirmation_id=confirmation.confirmation_id,
        nodes=tuple(node_plans),
        bindings=tuple(binding_plans),
        prompt_preparation_keys=tuple(preparation_keys),
        automatic_run_keys=(),
        created_at=datetime.now(timezone.utc),
    )


def _fanout_plan_id(confirmation: GuidedMediaConfirmationV1) -> str:
    return "fanout_" + sha256(confirmation.logical_identity.encode()).hexdigest()[:32]


def _retarget_binding_metadata(
    binding: CanvasBindingV2,
    *,
    target_role: str,
) -> dict[str, object]:
    if binding.metadata.get("context_kind") == "world_setting":
        return WorldSettingBindingPolicy().metadata_for_target(
            target_role,
            binding.metadata,
        )
    return dict(binding.metadata)


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
