"""Typed contracts for durable Agent-owned working documents."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


AgentWorkingDocumentKindV2 = Literal[
    "anchor_registry",
    "storyboard_production_plan",
]
AgentAnchorTypeV2 = Literal[
    "subject",
    "environment",
    "world_setting",
    "style",
    "composition",
]
AgentAnchorSourceKindV2 = Literal["node", "image_asset", "skill_snapshot"]
AgentAnchorAvailabilityV2 = Literal["pending", "available", "failed"]
StoryboardNodeRoleV2 = Literal[
    "storyboard_grid",
    "video_segment",
    "bgm",
    "editing",
]


class _WorkingDocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _AuthoritativeWorkingDocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


AgentAnchorSemanticRoleV3 = Literal[
    "world_setting",
    "product",
    "prop",
    "character",
    "scene",
    "style",
    "composition",
]
AgentAnchorLifecycleV3 = Literal["planned", "active", "retired", "invalid"]


class AgentAnchorNodeSourceV3(_AuthoritativeWorkingDocumentModel):
    source_kind: Literal["node"] = "node"
    workflow_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)


class AgentAnchorImageAssetVersionSourceV3(_AuthoritativeWorkingDocumentModel):
    source_kind: Literal["image_asset_version"] = "image_asset_version"
    workflow_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)


class AgentAnchorSkillSnapshotSourceV3(_AuthoritativeWorkingDocumentModel):
    source_kind: Literal["skill_snapshot"] = "skill_snapshot"
    skill_id: str = Field(min_length=1, max_length=160)
    skill_version: str = Field(min_length=1, max_length=160)
    package_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


AgentAnchorSourceV3: TypeAlias = Annotated[
    AgentAnchorNodeSourceV3
    | AgentAnchorImageAssetVersionSourceV3
    | AgentAnchorSkillSnapshotSourceV3,
    Field(discriminator="source_kind"),
]


class AnchorAcceptanceEvidenceV1(_AuthoritativeWorkingDocumentModel):
    evidence_id: str = Field(min_length=1, max_length=160)
    actor: Literal["user", "agent", "system"]
    decision: Literal["accepted", "delegated", "activated", "retired", "invalidated"]
    action_id: str = Field(min_length=1, max_length=160)
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_revision_no: int = Field(ge=1)
    node_revision: int | None = Field(default=None, ge=1)
    asset_version_id: str | None = Field(default=None, min_length=1, max_length=160)
    document_revision: int = Field(ge=1)
    recorded_at: datetime


class AgentAnchorV3(_AuthoritativeWorkingDocumentModel):
    alias: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,31}$")
    identity_id: str = Field(min_length=1, max_length=160)
    semantic_role: AgentAnchorSemanticRoleV3
    display_name: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=4_096)
    lifecycle: AgentAnchorLifecycleV3
    source: AgentAnchorSourceV3
    acceptance_evidence: tuple[AnchorAcceptanceEvidenceV1, ...] = Field(
        min_length=1,
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_source_evidence(self) -> "AgentAnchorV3":
        media_roles = {"product", "prop", "character", "scene"}
        if (
            self.lifecycle == "active"
            and self.semantic_role in media_roles
            and not isinstance(self.source, AgentAnchorImageAssetVersionSourceV3)
        ):
            raise ValueError("An active media anchor requires an image Asset version source.")
        if isinstance(self.source, AgentAnchorImageAssetVersionSourceV3):
            if not any(
                evidence.asset_version_id == self.source.asset_version_id
                and evidence.node_revision == self.source.node_revision
                for evidence in self.acceptance_evidence
            ):
                raise ValueError("Asset version source requires matching acceptance evidence.")
        if isinstance(self.source, AgentAnchorSkillSnapshotSourceV3):
            if self.semantic_role != "style":
                raise ValueError("A Skill snapshot source is valid only for a style anchor.")
        elif self.semantic_role == "style":
            raise ValueError("A style anchor requires an approved Skill snapshot source.")
        return self


class AnchorRegistryContentV3(_AuthoritativeWorkingDocumentModel):
    schema_version: Literal["3"]
    anchors: tuple[AgentAnchorV3, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def validate_identity_authority(self) -> "AnchorRegistryContentV3":
        aliases = [anchor.alias for anchor in self.anchors]
        if len(aliases) != len(set(aliases)):
            raise ValueError("Anchor aliases must be unique and cannot be rebound.")
        live_roles = [
            anchor.semantic_role
            for anchor in self.anchors
            if anchor.lifecycle in {"planned", "active"}
        ]
        if len(live_roles) != len(set(live_roles)):
            raise ValueError("Each semantic role can have only one current anchor.")
        return self

    def current_anchor(self, semantic_role: AgentAnchorSemanticRoleV3) -> AgentAnchorV3 | None:
        return next(
            (
                anchor
                for anchor in self.anchors
                if anchor.semantic_role == semantic_role
                and anchor.lifecycle in {"planned", "active"}
            ),
            None,
        )


class AgentAnchorV2(_WorkingDocumentModel):
    alias: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,15}$")
    anchor_type: AgentAnchorTypeV2
    display_name: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=4_096)
    source_kind: AgentAnchorSourceKindV2
    source_id: str | None = Field(default=None, max_length=160)
    availability: AgentAnchorAvailabilityV2

    @model_validator(mode="after")
    def validate_source_availability(self) -> "AgentAnchorV2":
        if self.availability == "available" and not self.source_id:
            raise ValueError("An available anchor requires a source id.")
        if self.availability == "pending" and self.source_id is not None:
            raise ValueError("A pending anchor cannot bind a source id.")
        return self


class AnchorRegistryContentV2(_WorkingDocumentModel):
    anchors: tuple[AgentAnchorV2, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def validate_aliases(self) -> "AnchorRegistryContentV2":
        aliases = [anchor.alias for anchor in self.anchors]
        if len(aliases) != len(set(aliases)):
            raise ValueError("Anchor aliases must be unique.")
        return self


class StoryboardPlanGlobalParametersV2(_WorkingDocumentModel):
    aspect_ratio: str = Field(min_length=1, max_length=32)
    total_duration_seconds: float = Field(gt=0, le=3_600)
    segment_count: int = Field(ge=1, le=128)


class StoryboardNarrativeSegmentV2(_WorkingDocumentModel):
    sequence_id: str = Field(min_length=1, max_length=160)
    order: int = Field(ge=1, le=128)
    start_seconds: float = Field(ge=0, le=3_600)
    end_seconds: float = Field(gt=0, le=3_600)
    narrative_goal: str = Field(min_length=1, max_length=4_096)
    start_state: str = Field(min_length=1, max_length=2_048)
    end_state: str = Field(min_length=1, max_length=2_048)
    continuity_from_previous: str | None = Field(default=None, max_length=2_048)
    terminal_policy: Literal["continue", "close"] | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> "StoryboardNarrativeSegmentV2":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Segment end time must be after its start time.")
        return self


class StoryboardPlanRowV2(_WorkingDocumentModel):
    shot_index: int = Field(ge=1, le=1_152)
    sequence_id: str = Field(min_length=1, max_length=160)
    panel_index: int = Field(ge=1, le=9)
    content_beat: str = Field(min_length=1, max_length=4_096)
    anchor_aliases: tuple[str, ...] = Field(default=(), max_length=64)
    camera_description: str = Field(min_length=1, max_length=4_096)

    @model_validator(mode="after")
    def validate_anchor_aliases(self) -> "StoryboardPlanRowV2":
        if len(self.anchor_aliases) != len(set(self.anchor_aliases)):
            raise ValueError("Storyboard row anchor aliases must be unique.")
        return self


class StoryboardNodeRecordV2(_WorkingDocumentModel):
    sequence_id: str | None = Field(default=None, max_length=160)
    node_role: StoryboardNodeRoleV2
    node_id: str = Field(min_length=1, max_length=160)


class StoryboardSegmentMaterializationV2(_WorkingDocumentModel):
    sequence_id: str = Field(min_length=1, max_length=160)
    status: Literal["pending", "materialized"] = "pending"
    generation_prompt: str | None = Field(default=None, max_length=16_384)


class StoryboardVisualAnchorV2(_WorkingDocumentModel):
    node_id: str = Field(min_length=1, max_length=160)
    asset_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    document_revision: int = Field(ge=1)


class AgentDocumentLinkedNodeRuntimeV2(_WorkingDocumentModel):
    node_id: str = Field(min_length=1, max_length=160)
    node_type: Literal["text", "script", "image", "video", "audio", "editing"]
    creative_role: str = Field(min_length=1, max_length=160)
    status: Literal["draft", "working", "ready", "failed"]
    revision: int = Field(ge=1)


class StoryboardProductionPlanContentV2(_WorkingDocumentModel):
    narrative_outline: str = Field(min_length=1, max_length=16_384)
    global_parameters: StoryboardPlanGlobalParametersV2
    segments: tuple[StoryboardNarrativeSegmentV2, ...] = Field(max_length=128)
    rows: tuple[StoryboardPlanRowV2, ...] = Field(max_length=1_152)
    node_records: tuple[StoryboardNodeRecordV2, ...] = Field(default=(), max_length=384)
    materialized_panel_cursor: int = Field(default=0, ge=0, le=1_152)
    segment_materializations: tuple[StoryboardSegmentMaterializationV2, ...] = Field(
        default=(), max_length=128
    )
    visual_anchor: StoryboardVisualAnchorV2 | None = None

    @model_validator(mode="after")
    def validate_plan_shape(self) -> "StoryboardProductionPlanContentV2":
        segment_count = self.global_parameters.segment_count
        if len(self.segments) != segment_count:
            raise ValueError("Segment count must match global parameters.")
        expected_orders = list(range(1, segment_count + 1))
        actual_orders = [segment.order for segment in self.segments]
        if actual_orders != expected_orders:
            raise ValueError("Storyboard segment order must be contiguous and ordered.")
        sequence_ids = [segment.sequence_id for segment in self.segments]
        if len(sequence_ids) != len(set(sequence_ids)):
            raise ValueError("Storyboard sequence ids must be unique.")
        previous_end = 0.0
        for segment in self.segments:
            if segment.start_seconds < previous_end:
                raise ValueError("Storyboard segment timing must not overlap.")
            if segment.end_seconds > self.global_parameters.total_duration_seconds:
                raise ValueError("Storyboard segment timing exceeds total duration.")
            previous_end = segment.end_seconds

        rows_by_sequence: dict[str, list[StoryboardPlanRowV2]] = defaultdict(list)
        for row in self.rows:
            if row.sequence_id not in sequence_ids:
                raise ValueError("Storyboard row references an unknown sequence.")
            rows_by_sequence[row.sequence_id].append(row)
        ordered_rows: list[StoryboardPlanRowV2] = []
        for sequence_id in sequence_ids:
            sequence_rows = rows_by_sequence[sequence_id]
            if len(sequence_rows) not in {0, 9}:
                raise ValueError("Each storyboard sequence requires zero or nine rows.")
            if not sequence_rows:
                continue
            if [row.panel_index for row in sequence_rows] != list(range(1, 10)):
                raise ValueError("Storyboard panel indices must be ordered from 1 through 9.")
            ordered_rows.extend(sequence_rows)
        if list(self.rows) != ordered_rows:
            raise ValueError("Storyboard rows must follow segment order.")
        if [row.shot_index for row in self.rows] != list(range(1, len(self.rows) + 1)):
            raise ValueError("Storyboard shot indices must be globally contiguous.")

        seen_node_records: set[tuple[str | None, StoryboardNodeRoleV2]] = set()
        for record in self.node_records:
            if record.sequence_id is not None and record.sequence_id not in sequence_ids:
                raise ValueError("Storyboard node record references an unknown sequence.")
            key = (record.sequence_id, record.node_role)
            if key in seen_node_records:
                raise ValueError("Storyboard node records must have unique roles per sequence.")
            seen_node_records.add(key)
        if self.segment_materializations:
            if [item.sequence_id for item in self.segment_materializations] != sequence_ids:
                raise ValueError("Storyboard materialization records must follow segments.")
            for item in self.segment_materializations:
                row_count = len(rows_by_sequence[item.sequence_id])
                if item.status == "pending" and (row_count or item.generation_prompt):
                    raise ValueError("Pending storyboard segments cannot contain generated rows.")
                if item.status == "materialized" and (row_count != 9 or not item.generation_prompt):
                    raise ValueError("Materialized storyboard segments require rows and prompt.")
        return self


class StoryboardPlannedNodeV3(_AuthoritativeWorkingDocumentModel):
    sequence_id: str | None = Field(default=None, max_length=160)
    node_role: StoryboardNodeRoleV2
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    materialization_id: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_sequence_scope(self) -> "StoryboardPlannedNodeV3":
        sequence_scoped = self.node_role in {"storyboard_grid", "video_segment"}
        if sequence_scoped != (self.sequence_id is not None):
            raise ValueError("Storyboard Grid and Video records require a sequence scope.")
        return self


class StoryboardVisualAnchorV3(_AuthoritativeWorkingDocumentModel):
    sequence_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    acceptance_evidence_id: str = Field(min_length=1, max_length=160)


class StoryboardProductionPlanContentV3(_AuthoritativeWorkingDocumentModel):
    schema_version: Literal["3"] = "3"
    narrative_outline: str = Field(min_length=1, max_length=16_384)
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_revision_no: int = Field(ge=1)
    global_parameters: StoryboardPlanGlobalParametersV2
    segments: tuple[StoryboardNarrativeSegmentV2, ...] = Field(max_length=128)
    rows: tuple[StoryboardPlanRowV2, ...] = Field(max_length=1_152)
    planned_nodes: tuple[StoryboardPlannedNodeV3, ...] = Field(default=(), max_length=384)
    visual_anchor: StoryboardVisualAnchorV3 | None = None

    @model_validator(mode="after")
    def validate_plan_authority(self) -> "StoryboardProductionPlanContentV3":
        segment_count = self.global_parameters.segment_count
        if len(self.segments) != segment_count:
            raise ValueError("Segment count must match global parameters.")
        if [segment.order for segment in self.segments] != list(range(1, segment_count + 1)):
            raise ValueError("Storyboard segment order must be contiguous and ordered.")
        sequence_ids = [segment.sequence_id for segment in self.segments]
        if len(sequence_ids) != len(set(sequence_ids)):
            raise ValueError("Storyboard sequence ids must be unique.")
        previous_end = 0.0
        for segment in self.segments:
            if segment.start_seconds < previous_end:
                raise ValueError("Storyboard segment timing must not overlap.")
            if segment.end_seconds > self.global_parameters.total_duration_seconds:
                raise ValueError("Storyboard segment timing exceeds total duration.")
            previous_end = segment.end_seconds

        rows_by_sequence: dict[str, list[StoryboardPlanRowV2]] = defaultdict(list)
        for row in self.rows:
            if row.sequence_id not in sequence_ids:
                raise ValueError("Storyboard row references an unknown sequence.")
            rows_by_sequence[row.sequence_id].append(row)
        ordered_rows: list[StoryboardPlanRowV2] = []
        for sequence_id in sequence_ids:
            sequence_rows = rows_by_sequence[sequence_id]
            if len(sequence_rows) not in {0, 9}:
                raise ValueError("Each materialized Storyboard sequence requires nine rows.")
            if sequence_rows and [row.panel_index for row in sequence_rows] != list(range(1, 10)):
                raise ValueError("Storyboard panel indices must be ordered from 1 through 9.")
            ordered_rows.extend(sequence_rows)
        if list(self.rows) != ordered_rows:
            raise ValueError("Storyboard rows must follow segment order.")
        if [row.shot_index for row in self.rows] != list(range(1, len(self.rows) + 1)):
            raise ValueError("Storyboard shot indices must be globally contiguous.")

        record_keys: set[tuple[str | None, StoryboardNodeRoleV2]] = set()
        for record in self.planned_nodes:
            if record.sequence_id is not None and record.sequence_id not in sequence_ids:
                raise ValueError("Planned Node references an unknown Storyboard sequence.")
            key = (record.sequence_id, record.node_role)
            if key in record_keys:
                raise ValueError("Planned Node roles must be unique within their scope.")
            record_keys.add(key)
        if self.visual_anchor is not None:
            first_sequence_id = sequence_ids[0]
            if self.visual_anchor.sequence_id != first_sequence_id:
                raise ValueError("The visual anchor must use the first sequence Grid.")
            if not any(
                record.sequence_id == first_sequence_id
                and record.node_role == "storyboard_grid"
                and record.node_id == self.visual_anchor.node_id
                for record in self.planned_nodes
            ):
                raise ValueError("The visual anchor must reference the planned first Grid Node.")
        return self


AgentWorkingDocumentContentV2 = Annotated[
    AnchorRegistryContentV3
    | StoryboardProductionPlanContentV3
    | AnchorRegistryContentV2
    | StoryboardProductionPlanContentV2,
    Field(union_mode="left_to_right"),
]


AgentWorkingDocumentContentV3 = Annotated[
    AnchorRegistryContentV3 | StoryboardProductionPlanContentV3,
    Field(union_mode="left_to_right"),
]


class AgentWorkingDocumentV2(_WorkingDocumentModel):
    document_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    guidance_session_id: str = Field(min_length=1, max_length=160)
    kind: AgentWorkingDocumentKindV2
    title: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1)
    content_schema_version: Literal[2, 3] = 2
    content_digest: str = Field(pattern=r"^sha256:[0-9a-zA-Z_-]+$")
    content: AgentWorkingDocumentContentV2
    created_by_agent_run_id: str = Field(min_length=1, max_length=160)
    updated_by_agent_run_id: str = Field(min_length=1, max_length=160)
    linked_nodes: tuple[AgentDocumentLinkedNodeRuntimeV2, ...] = ()
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_content_kind(self) -> "AgentWorkingDocumentV2":
        expected_types = (
            (AnchorRegistryContentV2, AnchorRegistryContentV3)
            if self.kind == "anchor_registry"
            else (StoryboardProductionPlanContentV2, StoryboardProductionPlanContentV3)
        )
        if not isinstance(self.content, expected_types):
            raise ValueError("Working document content does not match its kind.")
        actual_version = 3 if getattr(self.content, "schema_version", None) == "3" else 2
        if self.content_schema_version != actual_version:
            raise ValueError("Working document schema version does not match its content.")
        return self


class AgentWorkingDocumentPageV2(_WorkingDocumentModel):
    items: tuple[AgentWorkingDocumentV2, ...] = ()
    next_cursor: str | None = None


class AgentWorkingDocumentReferenceV2(_WorkingDocumentModel):
    type: Literal["agent_document_reference"] = "agent_document_reference"
    document_id: str = Field(min_length=1, max_length=160)
    document_kind: AgentWorkingDocumentKindV2
    revision: int = Field(ge=1)
    content_digest: str = Field(pattern=r"^sha256:[0-9a-zA-Z_-]+$")
    title: str = Field(min_length=1, max_length=256)


class AgentDocumentContextExcerptV2(_WorkingDocumentModel):
    document_id: str = Field(min_length=1, max_length=160)
    document_kind: AgentWorkingDocumentKindV2
    revision: int = Field(ge=1)
    content_digest: str = Field(pattern=r"^sha256:[0-9a-zA-Z_-]+$")
    selector: str = Field(min_length=1, max_length=512)
    content: dict[str, JsonValue]


class AgentDocumentProvenanceV2(_WorkingDocumentModel):
    source_agent_document_id: str = Field(min_length=1, max_length=160)
    source_agent_document_kind: AgentWorkingDocumentKindV2
    source_agent_document_revision: int = Field(ge=1)
    source_agent_document_digest: str = Field(pattern=r"^sha256:[0-9a-zA-Z_-]+$")
    source_agent_document_selector: str = Field(min_length=1, max_length=512)


class _AgentDocumentPatchBaseV2(_WorkingDocumentModel):
    document_id: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=256)


class InitializeAnchorRegistryPatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["initialize_anchor_registry"]
    anchors: tuple[AgentAnchorV2, ...] = Field(default=(), max_length=256)


class UpsertAnchorPatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["upsert_anchor"]
    anchor: AgentAnchorV2


class InitializeStoryboardPlanPatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["initialize_storyboard_plan"]
    content: StoryboardProductionPlanContentV2


class ReplaceNarrativeSegmentPatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["replace_narrative_segment"]
    segment: StoryboardNarrativeSegmentV2


class ReplaceStoryboardRowsPatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["replace_storyboard_rows"]
    sequence_id: str = Field(min_length=1, max_length=160)
    rows: tuple[StoryboardPlanRowV2, ...] = Field(min_length=9, max_length=9)


class MaterializeStoryboardSegmentPatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["materialize_storyboard_segment"]
    sequence_id: str = Field(min_length=1, max_length=160)
    rows: tuple[StoryboardPlanRowV2, ...] = Field(min_length=9, max_length=9)
    generation_prompt: str = Field(min_length=1, max_length=16_384)


class FreezeStoryboardVisualAnchorPatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["freeze_storyboard_visual_anchor"]
    visual_anchor: StoryboardVisualAnchorV2


class AttachStoryboardNodePatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["attach_storyboard_node"]
    sequence_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)


class AttachVideoNodePatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["attach_video_node"]
    sequence_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)


class AttachAudioNodePatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["attach_audio_node"]
    node_id: str = Field(min_length=1, max_length=160)


class AttachEditingNodePatchV2(_AgentDocumentPatchBaseV2):
    operation: Literal["attach_editing_node"]
    node_id: str = Field(min_length=1, max_length=160)


AgentDocumentPatchV2 = Annotated[
    InitializeAnchorRegistryPatchV2
    | UpsertAnchorPatchV2
    | InitializeStoryboardPlanPatchV2
    | ReplaceNarrativeSegmentPatchV2
    | ReplaceStoryboardRowsPatchV2
    | MaterializeStoryboardSegmentPatchV2
    | FreezeStoryboardVisualAnchorPatchV2
    | AttachStoryboardNodePatchV2
    | AttachVideoNodePatchV2
    | AttachAudioNodePatchV2
    | AttachEditingNodePatchV2,
    Field(discriminator="operation"),
]


class AgentDocumentPatchResultV2(_WorkingDocumentModel):
    document: AgentWorkingDocumentV2
    replayed: bool = False


class AgentDocumentMutationPlanV3(_AuthoritativeWorkingDocumentModel):
    document_id: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=1)
    next_revision: int = Field(ge=2)
    operation: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=256)
    request_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    next_content: AgentWorkingDocumentContentV2

    @model_validator(mode="after")
    def validate_revision_step(self) -> "AgentDocumentMutationPlanV3":
        if self.next_revision != self.expected_revision + 1:
            raise ValueError("A document mutation must advance exactly one revision.")
        return self


class AgentDocumentPatchSubmissionV2(_WorkingDocumentModel):
    """Closed Pi structured output for one internal document mutation."""

    patch: AgentDocumentPatchV2
