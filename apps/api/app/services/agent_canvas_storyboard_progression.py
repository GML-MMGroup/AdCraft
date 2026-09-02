"""Advance progressive storyboard Drafts after the first grid becomes Ready."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import SimpleNamespace
from sqlalchemy.engine import Connection
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
    StoryboardNodeRecordV2,
    StoryboardPlannedNodeV3,
    StoryboardProductionPlanContentV2,
    StoryboardProductionPlanContentV3,
    StoryboardVisualAnchorV2,
    StoryboardVisualAnchorV3,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_conversation import VideoAgentGateway
from app.services.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthoringService,
)
from app.services.agent_canvas_world_setting import WorldSettingBindingPolicy
from app.services.agent_canvas_role_reference_policy import (
    AgentCanvasRoleReferencePolicyService,
)
from app.services.agent_canvas_guided_media_parameters import (
    resolve_video_audio_parameter,
)
from app.services.agent_canvas_video_representation import resolve_video_representation_mode


BindingCapabilityValidator = Callable[[object, frozenset[str], int], object]
StoryboardPipelinePreparedCallback = Callable[[str, str], object]
VideoResolutionResolver = Callable[[str], str | None]
VideoAudioConstraintsResolver = Callable[[str], dict[str, object]]


@dataclass(frozen=True)
class StoryboardFanoutPreflightResult:
    """Immutable evidence used to fence the later local fan-out publication."""

    fanout_plan: StoryboardFanoutPlanV1
    preflight_digest: str


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
        video_resolution_resolver: VideoResolutionResolver | None = None,
        video_audio_constraints_resolver: VideoAudioConstraintsResolver | None = None,
        on_storyboard_pipeline_prepared: StoryboardPipelinePreparedCallback | None = None,
    ) -> None:
        self._workflows = workflows
        self._authoring = authoring
        self._gateway = gateway
        self._receipts = receipts
        self._asset_resolver = asset_resolver
        self._events = events
        self._binding_capability_validator = binding_capability_validator
        self._video_resolution_resolver = video_resolution_resolver
        self._video_audio_constraints_resolver = video_audio_constraints_resolver
        self._on_storyboard_pipeline_prepared = on_storyboard_pipeline_prepared

    def preflight_fanout(
        self,
        *,
        workflow_id: str,
        plan_document_id: str,
        source_grid: CanvasNodeV2,
        confirmation: GuidedMediaConfirmationV1,
    ) -> StoryboardFanoutPreflightResult:
        """Validate every planned member without publishing any durable state."""

        if source_grid.workflow_id != workflow_id:
            raise V2PersistenceError(
                "guided_media_confirmation_stale",
                "Storyboard fan-out source belongs to another workflow.",
                stage="storyboard_progression",
            )
        plan = next(
            (
                item
                for item in self._authoring.list_plans(workflow_id).items
                if item.document_id == plan_document_id
            ),
            None,
        )
        if plan is None:
            raise V2PersistenceError(
                "guided_media_confirmation_stale",
                "Storyboard fan-out Plan is not current.",
                stage="storyboard_progression",
            )
        content = _plan_content(plan.content)
        first_sequence = _first_sequence(content)
        if not any(
            record.node_id == source_grid.node_id
            and record.node_role == "storyboard_grid"
            and record.sequence_id == first_sequence.sequence_id
            for record in _planned_nodes(content)
        ):
            raise V2PersistenceError(
                "guided_media_confirmation_stale",
                "Storyboard fan-out source is not the first planned Grid.",
                stage="storyboard_progression",
            )
        if self._asset_resolver is None or source_grid.output_asset_id is None:
            raise V2PersistenceError(
                "guided_media_confirmation_required",
                "Storyboard fan-out requires an exact source Asset.",
                stage="storyboard_progression",
            )
        asset = self._asset_resolver(source_grid.output_asset_id)
        self._validate_confirmation(plan, source_grid, asset, confirmation)
        workflow = self._workflows.get_workflow(workflow_id)
        fanout_plan = _fanout_plan(
            plan_document_id=plan.document_id,
            # Anchor freezing is the first atomic document revision in the
            # publication phase; the receipt records that resulting revision.
            plan_revision=plan.revision + 1,
            workflow=workflow,
            content=content,
            grid_one=source_grid,
            asset=asset,
            confirmation=confirmation,
        )

        # Build future nodes in memory. This exercises the same representation,
        # capability, reference, and identity admission used after commit.
        virtual_nodes = list(workflow.nodes)
        virtual_bindings = list(workflow.bindings)
        video_resolution = self._resolve_video_resolution(workflow_id)
        for sequence in content.segments:
            if sequence.order == 1:
                grid = source_grid
            else:
                grid_id = _node_id(plan.document_id, sequence.sequence_id, "grid")
                grid = next((item for item in virtual_nodes if item.node_id == grid_id), None)
                if grid is None:
                    grid = _grid_node(
                        workflow_id=workflow_id,
                        node_id=grid_id,
                        order=sequence.order,
                        sequence=sequence,
                        segment=_accepted_segment(content, sequence.sequence_id),
                        source=source_grid,
                        plan_revision=plan.revision,
                    )
                    grid_bindings = _later_grid_bindings(
                        workflow=SimpleNamespace(
                            nodes=tuple(virtual_nodes),
                            bindings=tuple(virtual_bindings),
                        ),
                        grid_one=source_grid,
                        target=grid,
                    )
                    self._validate_grid_capacity(grid, grid_bindings)
                    virtual_nodes.append(grid)
                    virtual_bindings.extend(grid_bindings)
            video_id = _node_id(plan.document_id, sequence.sequence_id, "video")
            video = next((item for item in virtual_nodes if item.node_id == video_id), None)
            if video is None:
                video, video_bindings = self._build_video_node(
                    plan.document_id,
                    sequence.sequence_id,
                    grid,
                    plan_revision=plan.revision,
                    duration_seconds=sequence.end_seconds - sequence.start_seconds,
                    sequence_start_seconds=sequence.start_seconds,
                    sequence_end_seconds=sequence.end_seconds,
                    aspect_ratio=content.global_parameters.aspect_ratio,
                    resolution=video_resolution,
                    workflow=SimpleNamespace(
                        nodes=tuple(virtual_nodes),
                        bindings=tuple(virtual_bindings),
                    ),
                )
                self._validate_grid_capacity(video, video_bindings)
                virtual_nodes.append(video)
                virtual_bindings.extend(video_bindings)
        preflight_digest = self._preflight_digest(
            fanout_plan,
            source_grid=source_grid,
            asset=asset,
        )
        return StoryboardFanoutPreflightResult(
            fanout_plan=fanout_plan,
            preflight_digest=preflight_digest,
        )

    def publish_confirmation_and_fanout(
        self,
        *,
        source_grid: CanvasNodeV2,
        confirmation: GuidedMediaConfirmationV1,
    ) -> tuple[GuidedMediaConfirmationV1, tuple[str, ...]]:
        """Publish the first accepted Grid and all local fan-out state atomically."""

        if self._receipts is None or self._events is None or self._asset_resolver is None:
            raise V2PersistenceError(
                "storyboard_transaction_authority_required",
                "Storyboard fan-out requires shared receipt and event transaction authority.",
                stage="storyboard_progression",
            )
        preflight = self.preflight_fanout(
            workflow_id=source_grid.workflow_id,
            plan_document_id=confirmation.plan_document_id,
            source_grid=source_grid,
            confirmation=confirmation,
        )
        plan = next(
            (
                item
                for item in self._authoring.list_plans(source_grid.workflow_id).items
                if item.document_id == confirmation.plan_document_id
            ),
            None,
        )
        if plan is None:
            raise V2PersistenceError(
                "guided_media_confirmation_stale",
                "Storyboard fan-out Plan is not current.",
                stage="storyboard_progression",
            )
        content = _plan_content(plan.content)
        workflow = self._workflows.get_workflow(source_grid.workflow_id)
        asset = self._asset_resolver(confirmation.asset_id)
        self._validate_confirmation(plan, source_grid, asset, confirmation)
        expected_digest = self._preflight_digest(
            preflight.fanout_plan,
            source_grid=source_grid,
            asset=asset,
        )
        if expected_digest != preflight.preflight_digest:
            raise V2PersistenceError(
                "storyboard_fanout_preflight_stale",
                "Storyboard fan-out preflight evidence changed before publication.",
                stage="storyboard_progression",
            )

        members = self._build_fanout_members(
            workflow=workflow,
            plan_document_id=plan.document_id,
            plan_revision=plan.revision,
            content=content,
            source_grid=source_grid,
        )
        next_content = _published_plan_content(
            content,
            plan_document_id=plan.document_id,
            plan_revision=plan.revision,
            source_grid=source_grid,
            confirmation=confirmation,
            members=members,
            fanout=preflight.fanout_plan,
            existing_nodes=workflow.nodes,
        )
        agent_run_id = f"storyboard-fanout:{preflight.fanout_plan.fanout_plan_id}"
        event_time = datetime.now(timezone.utc).isoformat()
        try:
            with self._workflows.database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    self._workflows.require_node_revision_in_transaction(
                        connection,
                        workflow_id=source_grid.workflow_id,
                        node_id=source_grid.node_id,
                        expected_revision=source_grid.revision,
                        expected_output_asset_id=source_grid.output_asset_id,
                    )
                    stored_confirmation = self._receipts.save_confirmation_in_transaction(
                        connection,
                        confirmation,
                    )
                    current_workflow_revision = workflow.revision
                    created_node_ids: list[str] = []
                    for node, bindings in members:
                        current_workflow_revision = (
                            self._workflows.add_node_with_bindings_in_transaction(
                                connection,
                                node,
                                bindings,
                                expected_revision=current_workflow_revision,
                            )
                        )
                        created_node_ids.append(node.node_id)
                    self._authoring.commit_plan_content_in_transaction(
                        connection,
                        workflow_id=source_grid.workflow_id,
                        agent_run_id=agent_run_id,
                        document_id=plan.document_id,
                        expected_revision=plan.revision,
                        operation="publish_storyboard_fanout",
                        idempotency_key=preflight.fanout_plan.fanout_plan_id,
                        next_content=next_content,
                    )
                    fanout = self._receipts.save_fanout_in_transaction(
                        connection,
                        preflight.fanout_plan,
                    )
                    self._append_publication_events_in_transaction(
                        connection,
                        confirmation=stored_confirmation,
                        fanout=fanout,
                        event_time=event_time,
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        if created_node_ids and self._on_storyboard_pipeline_prepared is not None:
            self._on_storyboard_pipeline_prepared(
                source_grid.workflow_id,
                confirmation.plan_document_id,
            )
        return stored_confirmation, tuple(created_node_ids)

    def _build_fanout_members(
        self,
        *,
        workflow,
        plan_document_id: str,
        plan_revision: int,
        content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
        source_grid: CanvasNodeV2,
    ) -> tuple[tuple[CanvasNodeV2, tuple[CanvasBindingV2, ...]], ...]:
        virtual_nodes = list(workflow.nodes)
        virtual_bindings = list(workflow.bindings)
        members: list[tuple[CanvasNodeV2, tuple[CanvasBindingV2, ...]]] = []
        video_resolution = self._resolve_video_resolution(source_grid.workflow_id)
        for sequence in content.segments:
            if sequence.order == 1:
                grid = source_grid
            else:
                grid_id = _node_id(plan_document_id, sequence.sequence_id, "grid")
                grid = next((item for item in virtual_nodes if item.node_id == grid_id), None)
                if grid is None:
                    grid = _grid_node(
                        workflow_id=source_grid.workflow_id,
                        node_id=grid_id,
                        order=sequence.order,
                        sequence=sequence,
                        segment=_accepted_segment(content, sequence.sequence_id),
                        source=source_grid,
                        plan_revision=plan_revision,
                    )
                    grid_bindings = _later_grid_bindings(
                        workflow=SimpleNamespace(
                            nodes=tuple(virtual_nodes),
                            bindings=tuple(virtual_bindings),
                        ),
                        grid_one=source_grid,
                        target=grid,
                    )
                    self._validate_grid_capacity(grid, grid_bindings)
                    members.append((grid, grid_bindings))
                    virtual_nodes.append(grid)
                    virtual_bindings.extend(grid_bindings)
            video_id = _node_id(plan_document_id, sequence.sequence_id, "video")
            if any(item.node_id == video_id for item in virtual_nodes):
                continue
            video, video_bindings = self._build_video_node(
                plan_document_id,
                sequence.sequence_id,
                grid,
                plan_revision=plan_revision,
                duration_seconds=sequence.end_seconds - sequence.start_seconds,
                sequence_start_seconds=sequence.start_seconds,
                sequence_end_seconds=sequence.end_seconds,
                aspect_ratio=content.global_parameters.aspect_ratio,
                resolution=video_resolution,
                workflow=SimpleNamespace(
                    nodes=tuple(virtual_nodes),
                    bindings=tuple(virtual_bindings),
                ),
            )
            self._validate_grid_capacity(video, video_bindings)
            members.append((video, video_bindings))
            virtual_nodes.append(video)
            virtual_bindings.extend(video_bindings)
        return tuple(members)

    @staticmethod
    def _preflight_digest(
        fanout_plan: StoryboardFanoutPlanV1,
        *,
        source_grid: CanvasNodeV2,
        asset: ProjectAssetSummaryV2,
    ) -> str:
        return sha256(
            json.dumps(
                {
                    "fanout_plan": fanout_plan.model_dump(mode="json"),
                    "source_grid_revision": source_grid.revision,
                    "source_asset_id": source_grid.output_asset_id,
                    "source_asset_version_id": asset.version_id,
                    "source_asset_digest": asset.checksum,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def _append_publication_events_in_transaction(
        self,
        connection: Connection,
        *,
        confirmation: GuidedMediaConfirmationV1,
        fanout: StoryboardFanoutPlanV1,
        event_time: str,
    ) -> None:
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=fanout.workflow_id,
                node_id=fanout.visual_anchor_node_id,
                event_type="storyboard_visual_anchor_frozen",
                transition_key=f"storyboard_visual_anchor_frozen:{fanout.plan_document_id}",
                created_at=event_time,
                payload={
                    "node_id": fanout.visual_anchor_node_id,
                    "asset_id": fanout.visual_anchor_asset_id,
                    "asset_version_id": fanout.visual_anchor_asset_version_id,
                    "plan_document_id": fanout.plan_document_id,
                    "plan_revision": fanout.plan_revision,
                },
            ),
        )
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=confirmation.workflow_id,
                node_id=confirmation.node_id,
                event_type="guided_media_confirmed",
                transition_key=f"guided-media-confirmed:{confirmation.confirmation_id}",
                action_id=confirmation.action_id,
                created_at=confirmation.confirmed_at.isoformat(),
                payload={
                    "confirmation_id": confirmation.confirmation_id,
                    "plan_document_id": confirmation.plan_document_id,
                    "plan_revision": confirmation.plan_revision,
                    "node_revision": confirmation.node_revision,
                    "asset_id": confirmation.asset_id,
                    "asset_version_id": confirmation.asset_version_id,
                    "asset_digest": confirmation.asset_digest,
                    "accepted_by": confirmation.accepted_by,
                    "sequence_id": confirmation.sequence_id,
                    "media_role": confirmation.media_role,
                },
            ),
        )
        for event in _fanout_events(fanout, event_time=event_time):
            self._events.append_in_transaction(connection, event)

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
                    and record.sequence_id == _first_sequence(item.content).sequence_id
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
            return self._materialize_sibling_branch(
                plan.document_id,
                plan.revision,
                content,
                node,
            )
        replay: StoryboardFanoutPlanV1 | None = None
        preflight: StoryboardFanoutPreflightResult | None = None
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
                _confirmation, created_node_ids = self.publish_confirmation_and_fanout(
                    source_grid=node,
                    confirmation=confirmation,
                )
                return created_node_ids
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
            if preflight is None:
                raise V2PersistenceError(
                    "storyboard_fanout_invalid",
                    "Storyboard fan-out preflight evidence is required.",
                    stage="storyboard_progression",
                )
            fanout_authority = self._receipts.save_fanout(preflight.fanout_plan)
        first_sequence = _first_sequence(content)
        video_resolution = self._resolve_video_resolution(node.workflow_id)
        created.extend(
            self._ensure_video(
                plan.document_id,
                first_sequence.sequence_id,
                node,
                plan_revision=plan.revision,
                duration_seconds=first_sequence.end_seconds - first_sequence.start_seconds,
                sequence_start_seconds=first_sequence.start_seconds,
                sequence_end_seconds=first_sequence.end_seconds,
                aspect_ratio=content.global_parameters.aspect_ratio,
                resolution=video_resolution,
            )
        )
        for sequence in _later_sequences(content):
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
                    plan_revision=plan.revision,
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
                    plan_revision=plan.revision,
                    duration_seconds=sequence.end_seconds - sequence.start_seconds,
                    sequence_start_seconds=sequence.start_seconds,
                    sequence_end_seconds=sequence.end_seconds,
                    aspect_ratio=content.global_parameters.aspect_ratio,
                    resolution=video_resolution,
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
            and confirmation.sequence_id == _first_sequence(plan.content).sequence_id
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
        plan_revision: int,
        content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
        grid_one: CanvasNodeV2,
    ) -> tuple[str, ...]:
        branch_scope = f"{plan_document_id}:{grid_one.node_id}"
        created: list[str] = []
        first_sequence = _first_sequence(content)
        video_resolution = self._resolve_video_resolution(grid_one.workflow_id)
        created.extend(
            self._ensure_video(
                plan_document_id,
                first_sequence.sequence_id,
                grid_one,
                plan_revision=plan_revision,
                duration_seconds=(first_sequence.end_seconds - first_sequence.start_seconds),
                sequence_start_seconds=first_sequence.start_seconds,
                sequence_end_seconds=first_sequence.end_seconds,
                aspect_ratio=content.global_parameters.aspect_ratio,
                resolution=video_resolution,
                node_identity_scope=branch_scope,
                attach_to_plan=False,
            )
        )
        for sequence in _later_sequences(content):
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
                    plan_revision=plan_revision,
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
                    plan_revision=plan_revision,
                    duration_seconds=sequence.end_seconds - sequence.start_seconds,
                    sequence_start_seconds=sequence.start_seconds,
                    sequence_end_seconds=sequence.end_seconds,
                    aspect_ratio=content.global_parameters.aspect_ratio,
                    resolution=video_resolution,
                    node_identity_scope=branch_scope,
                    attach_to_plan=False,
                )
            )
        return tuple(created)

    def _resolve_video_resolution(self, workflow_id: str) -> str | None:
        if self._video_resolution_resolver is None:
            return None
        resolution = self._video_resolution_resolver(workflow_id)
        return resolution.strip() if resolution and resolution.strip() else None

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

    def _build_video_node(
        self,
        plan_document_id: str,
        sequence_id: str,
        grid: CanvasNodeV2,
        *,
        plan_revision: int,
        duration_seconds: float,
        sequence_start_seconds: float,
        sequence_end_seconds: float,
        aspect_ratio: str,
        resolution: str | None,
        node_identity_scope: str | None = None,
        workflow=None,
    ) -> tuple[CanvasNodeV2, tuple[CanvasBindingV2, ...]]:
        video_id = _node_id(
            node_identity_scope or plan_document_id,
            sequence_id,
            "video",
        )
        workflow = workflow or self._workflows.get_workflow(grid.workflow_id)
        if any(item.node_id == video_id for item in workflow.nodes):
            raise V2PersistenceError(
                "storyboard_fanout_conflict",
                "Storyboard Video identity already exists during fan-out preparation.",
                stage="storyboard_progression",
            )
        content = StoryboardGridContentV2.model_validate(grid.structured_content)
        audio_constraints = (
            self._video_audio_constraints_resolver(grid.workflow_id)
            if self._video_audio_constraints_resolver is not None
            else {}
        )
        representation = resolve_video_representation_mode(
            explicit_control=audio_constraints.get("video_representation_mode"),
            skill_mode=audio_constraints.get("_video_skill_representation_mode"),
            skill_source_id=str(
                audio_constraints.get("_video_skill_representation_source_id") or "video-skill"
            ),
            identity_safety_decision=audio_constraints.get("identity_safety_decision"),
        )
        video_content = VideoSegmentContentV2(
            segment_summary=content.sequence_summary,
            duration_seconds=duration_seconds,
            storyboard_content="Follow the nine ordered storyboard frames.",
            representation_mode=representation.mode,
            environment_sound="Preserve scene ambience.",
            action_effects="Preserve declared action sounds.",
            background_music=False,
        )
        generate_audio, audio_provenance = resolve_video_audio_parameter(
            structured_values=video_content,
            explicit_constraints=audio_constraints,
        )
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
                f"Exact Storyboard Production Plan segment for {sequence_id}: "
                f"{grid.generation_prompt or grid.summary_prompt or ''}\n"
                "Use the complete matching storyboard grid as the primary ordered reference. "
                "Lock the opening frame to panel 1 without requiring a cropped panel asset, "
                "then follow panels 1 through 9 as one continuous commercial segment. "
                "Preserve required dialogue, voice performance, native ambience, movement, "
                "and synchronized action effects. Generate no background music."
            ),
            structured_content=video_content.model_dump(mode="json"),
            parameters={
                "duration_seconds": duration_seconds,
                "aspect_ratio": aspect_ratio,
                **({"resolution": resolution} if resolution is not None else {}),
                **({"generate_audio": generate_audio} if generate_audio is not None else {}),
            },
            parameter_provenance=(
                {"generate_audio": audio_provenance} if audio_provenance is not None else {}
            ),
            metadata={
                "source_agent_document_id": plan_document_id,
                "source_sequence_id": sequence_id,
                "source_plan_revision": plan_revision,
                "source_sequence_window": {
                    "start_seconds": sequence_start_seconds,
                    "end_seconds": sequence_end_seconds,
                },
                "video_representation_mode": representation.mode,
                "video_representation_source": representation.source,
                "video_representation_policy_version": representation.policy_version,
                "video_representation_digest": representation.digest,
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
            and _grid_source_role(binding, {node.node_id: node for node in workflow.nodes})
            in {"character_turnaround", "scene_board"}
        )
        bound_source_ids = {
            binding.source.source_node_id
            for binding in element_bindings
            if binding.source.kind == "node_output"
        }
        identity_bindings: list[CanvasBindingV2] = list(element_bindings)
        for source_role, source_node in _video_identity_nodes(workflow):
            if source_node.node_id in bound_source_ids:
                continue
            identity_bindings.append(
                CanvasBindingV2(
                    binding_id=_binding_id(video_id, "identity", len(identity_bindings) + 1),
                    workflow_id=grid.workflow_id,
                    source=CanvasBindingSourceNodeV2(source_node_id=source_node.node_id),
                    target_node_id=video.node_id,
                    input_role="image_reference",
                    required=True,
                    order=len(identity_bindings) + 1,
                    metadata={
                        "semantic_reference_role": _video_semantic_reference_role(source_role),
                    },
                    created_at=now,
                    updated_at=now,
                )
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
                for index, binding in enumerate(identity_bindings, start=1)
            ),
        )
        return video, bindings

    def _ensure_video(
        self,
        plan_document_id: str,
        sequence_id: str,
        grid: CanvasNodeV2,
        *,
        plan_revision: int,
        duration_seconds: float,
        sequence_start_seconds: float,
        sequence_end_seconds: float,
        aspect_ratio: str,
        resolution: str | None,
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
        video, bindings = self._build_video_node(
            plan_document_id,
            sequence_id,
            grid,
            plan_revision=plan_revision,
            duration_seconds=duration_seconds,
            sequence_start_seconds=sequence_start_seconds,
            sequence_end_seconds=sequence_end_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            node_identity_scope=node_identity_scope,
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
    nodes = {node.node_id: node for node in workflow.nodes}
    copied: list[CanvasBindingV2] = []
    source_roles: list[str] = []
    for binding in workflow.bindings:
        if binding.target_node_id != grid_one.node_id:
            continue
        source_role = _grid_source_role(binding, nodes)
        if source_role not in {"character_turnaround", "scene_board"}:
            continue
        copied.append(binding)
        source_roles.append(source_role)
    self_policy = AgentCanvasRoleReferencePolicyService()
    self_policy.require(
        "storyboard_grid_n",
        (*source_roles, "storyboard_grid_1"),
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


def _grid_source_role(binding: CanvasBindingV2, nodes: dict[str, CanvasNodeV2]) -> str | None:
    """Resolve only the role identity allowed to cross the guided Grid boundary."""

    if binding.input_role != "image_reference":
        return None
    if binding.source.kind == "node_output":
        source = nodes.get(binding.source.source_node_id)
        if source is None:
            return None
        if source.creative_role == "scene":
            return "scene_board"
        if (
            source.creative_role == "character"
            and source.structured_content.get("character_asset_kind") == "turnaround"
        ):
            return "character_turnaround"
        return None
    semantic_role = binding.metadata.get("semantic_reference_role")
    return {
        "subject_reference": "character_turnaround",
        "environment_reference": "scene_board",
    }.get(str(semantic_role))


def _video_identity_nodes(workflow) -> tuple[tuple[str, object], ...]:
    """Return the canonical guided identity set in provider order."""

    selected: list[tuple[str, object]] = []
    for node in workflow.nodes:
        role = None
        if node.creative_role == "product" and (
            node.structured_content.get("asset_kind") == "multi_view"
            or node.metadata.get("source_input_kind") == "multiview"
        ):
            role = "product_multiview"
        elif node.creative_role == "prop":
            role = "prop"
        elif (
            node.creative_role == "character"
            and node.structured_content.get("character_asset_kind") == "turnaround"
        ):
            role = "character_turnaround"
        elif node.creative_role == "scene":
            role = "scene_board"
        if role is not None:
            selected.append((role, node))
    return tuple(selected)


def _video_semantic_reference_role(source_role: str) -> str:
    return {
        "product_multiview": "product_reference",
        "prop": "prop_reference",
        "character_turnaround": "subject_reference",
        "scene_board": "environment_reference",
    }[source_role]


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
    records = tuple(getattr(content, "segment_materializations", ()))
    record = next((item for item in records if item.sequence_id == sequence_id), None)
    if isinstance(content, StoryboardProductionPlanContentV3) and (
        record is None or record.status != "materialized" or not record.generation_prompt
    ):
        raise V2PersistenceError(
            "storyboard_fanout_invalid",
            "Storyboard fan-out requires a current materialization record for the sequence.",
            stage="storyboard_progression",
            details={"sequence_id": sequence_id},
        )
    generation_prompt = record.generation_prompt if record is not None else None
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


def _first_sequence(
    content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
):
    sequence = next((item for item in content.segments if item.order == 1), None)
    if sequence is None:
        raise V2PersistenceError(
            "storyboard_fanout_invalid",
            "Storyboard fan-out requires an explicitly ordered first sequence.",
            stage="storyboard_progression",
        )
    return sequence


def _later_sequences(
    content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
):
    first = _first_sequence(content)
    return tuple(
        sorted(
            (item for item in content.segments if item.sequence_id != first.sequence_id),
            key=lambda item: item.order,
        )
    )


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


def _published_plan_content(
    content: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
    *,
    plan_document_id: str,
    plan_revision: int,
    source_grid: CanvasNodeV2,
    confirmation: GuidedMediaConfirmationV1,
    members: tuple[tuple[CanvasNodeV2, tuple[CanvasBindingV2, ...]], ...],
    fanout: StoryboardFanoutPlanV1,
    existing_nodes: tuple[CanvasNodeV2, ...],
) -> StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3:
    nodes_by_id = {node.node_id: node for node in existing_nodes}
    nodes_by_id.update({node.node_id: node for node, _bindings in members})
    planned = tuple(
        nodes_by_id[item.node_id] for item in fanout.nodes if item.node_id in nodes_by_id
    )
    if isinstance(content, StoryboardProductionPlanContentV3):
        existing = {(item.sequence_id, item.node_role) for item in content.planned_nodes}
        planned_nodes = list(content.planned_nodes)
        for node in planned:
            sequence_id = str(node.metadata["source_sequence_id"])
            node_role = "storyboard_grid" if node.node_type == "image" else "video_segment"
            if (sequence_id, node_role) in existing:
                continue
            planned_nodes.append(
                StoryboardPlannedNodeV3(
                    sequence_id=sequence_id,
                    node_role=node_role,
                    node_id=node.node_id,
                    node_revision=node.revision,
                    materialization_id=(
                        "materialization_"
                        + sha256(
                            f"{plan_document_id}:{sequence_id}:{node_role}:{node.node_id}".encode()
                        ).hexdigest()[:32]
                    ),
                )
            )
        return content.model_copy(
            update={
                "planned_nodes": tuple(planned_nodes),
                "visual_anchor": StoryboardVisualAnchorV3(
                    sequence_id=_first_sequence(content).sequence_id,
                    node_id=source_grid.node_id,
                    node_revision=source_grid.revision,
                    asset_id=confirmation.asset_id,
                    asset_version_id=confirmation.asset_version_id,
                    acceptance_evidence_id=confirmation.confirmation_id,
                ),
            }
        )

    existing = {(item.sequence_id, item.node_role) for item in content.node_records}
    records = list(content.node_records)
    for node in planned:
        sequence_id = str(node.metadata["source_sequence_id"])
        node_role = "storyboard_grid" if node.node_type == "image" else "video_segment"
        if (sequence_id, node_role) in existing:
            continue
        records.append(
            StoryboardNodeRecordV2(
                sequence_id=sequence_id,
                node_role=node_role,
                node_id=node.node_id,
            )
        )
    return content.model_copy(
        update={
            "node_records": tuple(records),
            "visual_anchor": StoryboardVisualAnchorV2(
                node_id=source_grid.node_id,
                asset_id=confirmation.asset_id,
                node_revision=source_grid.revision,
                document_revision=plan_revision,
            ),
        }
    )


def _fanout_events(
    fanout: StoryboardFanoutPlanV1,
    *,
    event_time: str,
) -> tuple[V2EventInsert, V2EventInsert]:
    return (
        V2EventInsert(
            workflow_id=fanout.workflow_id,
            node_id=fanout.visual_anchor_node_id,
            event_type="storyboard_visual_anchor_confirmed",
            transition_key=(
                f"storyboard-visual-anchor-confirmed:{fanout.visual_anchor_confirmation_id}"
            ),
            created_at=event_time,
            payload={
                "fanout_plan_id": fanout.fanout_plan_id,
                "confirmation_id": fanout.visual_anchor_confirmation_id,
                "node_revision": fanout.visual_anchor_node_revision,
                "asset_id": fanout.visual_anchor_asset_id,
                "asset_version_id": fanout.visual_anchor_asset_version_id,
                "plan_document_id": fanout.plan_document_id,
                "plan_revision": fanout.plan_revision,
            },
        ),
        V2EventInsert(
            workflow_id=fanout.workflow_id,
            node_id=fanout.visual_anchor_node_id,
            event_type="storyboard_fanout_committed",
            transition_key=f"storyboard-fanout-committed:{fanout.fanout_plan_id}",
            created_at=event_time,
            payload={
                "fanout_plan_id": fanout.fanout_plan_id,
                "plan_document_id": fanout.plan_document_id,
                "plan_revision": fanout.plan_revision,
                "planned_node_ids": [item.node_id for item in fanout.nodes],
                "planned_binding_ids": [item.binding_id for item in fanout.bindings],
            },
        ),
    )


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
    plan_revision: int,
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
        parameters={},
        metadata={
            "source_sequence_id": sequence.sequence_id,
            "source_plan_revision": plan_revision,
            "source_sequence_start_seconds": sequence.start_seconds,
            "source_sequence_end_seconds": sequence.end_seconds,
        },
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
