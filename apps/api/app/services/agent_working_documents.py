"""Deterministic validation and mutation of Agent working documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_working_document_repository import (
    AgentWorkingDocumentRepository,
)
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.models import AgentCanvasNodeRow, WorkflowRow
from app.schemas.agent_working_documents import (
    AgentAnchorImageAssetVersionSourceV3,
    AgentAnchorNodeSourceV3,
    AgentAnchorSkillSnapshotSourceV3,
    AgentAnchorV3,
    AgentWorkingDocumentContentV2,
    AgentAnchorV2,
    AgentDocumentContextExcerptV2,
    AgentDocumentLinkedNodeRuntimeV2,
    AgentDocumentMutationPlanV3,
    AgentDocumentPatchResultV2,
    AgentDocumentPatchV2,
    AgentWorkingDocumentV2,
    AgentWorkingDocumentKindV2,
    AgentWorkingDocumentPageV2,
    AnchorRegistryContentV2,
    AnchorRegistryContentV3,
    AttachAudioNodePatchV2,
    AttachEditingNodePatchV2,
    AttachStoryboardNodePatchV2,
    AttachVideoNodePatchV2,
    InitializeAnchorRegistryPatchV2,
    InitializeStoryboardPlanPatchV2,
    MaterializeStoryboardSegmentPatchV2,
    FreezeStoryboardVisualAnchorPatchV2,
    ReplaceNarrativeSegmentPatchV2,
    ReplaceStoryboardRowsPatchV2,
    StoryboardNodeRecordV2,
    StoryboardProductionPlanContentV2,
    StoryboardProductionPlanContentV3,
    UpsertAnchorPatchV2,
)


class AgentWorkingDocumentService:
    """Apply typed Agent patches while preserving Canvas authority boundaries."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        documents: AgentWorkingDocumentRepository,
        assets: V2AssetLibraryRepository,
        conversations: AgentCanvasConversationRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        database = workflows.database
        if (
            documents.database is not database
            or assets.database is not database
            or conversations.database is not database
        ):
            raise ValueError("Agent working document services must share one database.")
        self._workflows = workflows
        self._documents = documents
        self._assets = assets
        self._conversations = conversations
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_or_create_anchor_registry(
        self,
        *,
        workflow_id: str,
        guidance_session_id: str,
        agent_run_id: str,
        title: str = "Anchor Registry",
    ) -> AgentWorkingDocumentV2:
        self._require_scope(workflow_id, guidance_session_id)
        existing = self._documents.get_by_kind(
            workflow_id,
            guidance_session_id,
            "anchor_registry",
        )
        if existing is not None:
            return existing
        return self._documents.create(
            workflow_id=workflow_id,
            guidance_session_id=guidance_session_id,
            kind="anchor_registry",
            title=title,
            content=AnchorRegistryContentV2(),
            agent_run_id=agent_run_id,
            now=self._clock(),
        )

    def get_or_create_storyboard_plan(
        self,
        *,
        workflow_id: str,
        guidance_session_id: str,
        agent_run_id: str,
        content: StoryboardProductionPlanContentV2,
        title: str = "Storyboard Production Plan",
    ) -> AgentWorkingDocumentV2:
        self._require_scope(workflow_id, guidance_session_id)
        existing = self._documents.get_by_kind(
            workflow_id,
            guidance_session_id,
            "storyboard_production_plan",
        )
        if existing is not None:
            return existing
        self._validate_storyboard_content(
            workflow_id,
            guidance_session_id,
            content,
        )
        computed = _with_computed_cursor(content)
        return self._documents.create(
            workflow_id=workflow_id,
            guidance_session_id=guidance_session_id,
            kind="storyboard_production_plan",
            title=title,
            content=computed,
            agent_run_id=agent_run_id,
            now=self._clock(),
        )

    def get_document(
        self,
        workflow_id: str,
        document_id: str,
    ) -> AgentWorkingDocumentV2:
        self._require_agent_canvas(workflow_id)
        document = self._documents.get(document_id)
        if document is None:
            raise _error(
                "agent_document_not_found",
                "Agent working document was not found.",
            )
        if document.workflow_id != workflow_id:
            raise _error(
                "agent_document_workflow_mismatch",
                "Agent working document belongs to another workflow.",
            )
        return self.project_for_read(document)

    def list_documents(
        self,
        workflow_id: str,
        *,
        kind: AgentWorkingDocumentKindV2 | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> AgentWorkingDocumentPageV2:
        self._require_agent_canvas(workflow_id)
        page = self._documents.list(
            workflow_id,
            kind=kind,
            cursor=cursor,
            limit=limit,
        )
        return page.model_copy(
            update={"items": tuple(self.project_for_read(item) for item in page.items)}
        )

    def project_for_read(
        self,
        document: AgentWorkingDocumentV2,
    ) -> AgentWorkingDocumentV2:
        if document.kind != "storyboard_production_plan":
            return document.model_copy(update={"linked_nodes": ()})
        content = cast(StoryboardProductionPlanContentV2, document.content)
        records = (
            content.planned_nodes
            if isinstance(content, StoryboardProductionPlanContentV3)
            else content.node_records
        )
        workflow = self._workflows.get_workflow(document.workflow_id)
        nodes_by_id = {node.node_id: node for node in workflow.nodes}
        linked_nodes = tuple(
            AgentDocumentLinkedNodeRuntimeV2(
                node_id=node.node_id,
                node_type=node.node_type,
                creative_role=node.creative_role,
                status=node.status,
                revision=node.revision,
            )
            for record in records
            if (node := nodes_by_id.get(record.node_id)) is not None
        )
        return document.model_copy(update={"linked_nodes": linked_nodes})

    def apply_agent_patch(
        self,
        workflow_id: str,
        agent_run_id: str,
        patch: AgentDocumentPatchV2,
    ) -> AgentDocumentPatchResultV2:
        request_digest = self._documents.digest_patch(
            patch,
            agent_run_id=agent_run_id,
        )
        replay = self._documents.get_patch_replay(
            document_id=patch.document_id,
            idempotency_key=patch.idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return AgentDocumentPatchResultV2(
                document=self.project_for_read(replay),
                replayed=True,
            )
        mutation = self.plan_agent_patch(workflow_id, agent_run_id, patch)
        updated = self._documents.apply_patch(
            document_id=mutation.document_id,
            expected_revision=mutation.expected_revision,
            operation=mutation.operation,
            content=mutation.next_content,
            agent_run_id=agent_run_id,
            idempotency_key=mutation.idempotency_key,
            now=self._clock(),
            request_digest=mutation.request_digest,
        )
        return AgentDocumentPatchResultV2(document=self.project_for_read(updated))

    def plan_agent_patch(
        self,
        workflow_id: str,
        agent_run_id: str,
        patch: AgentDocumentPatchV2,
    ) -> AgentDocumentMutationPlanV3:
        """Validate one document mutation without committing accepted authority."""

        current = self.get_document(workflow_id, patch.document_id)
        if current.revision != patch.expected_revision:
            raise V2PersistenceError(
                "agent_document_revision_conflict",
                "Agent working document changed before this patch.",
                stage="agent_working_documents",
                details={"current_revision": current.revision},
            )
        return AgentDocumentMutationPlanV3(
            document_id=current.document_id,
            expected_revision=current.revision,
            next_revision=current.revision + 1,
            operation=patch.operation,
            idempotency_key=patch.idempotency_key,
            request_digest=self._documents.digest_patch(
                patch,
                agent_run_id=agent_run_id,
            ),
            next_content=self._apply_patch(current, patch),
        )

    def plan_content_mutation(
        self,
        *,
        workflow_id: str,
        agent_run_id: str,
        document_id: str,
        expected_revision: int,
        operation: str,
        idempotency_key: str,
        next_content: AgentWorkingDocumentContentV2,
    ) -> AgentDocumentMutationPlanV3:
        """Validate authoritative next content without committing it."""

        current = self.get_document(workflow_id, document_id)
        if current.revision != expected_revision:
            raise V2PersistenceError(
                "agent_document_revision_conflict",
                "Agent working document changed before this mutation.",
                stage="agent_working_documents",
                details={"current_revision": current.revision},
            )
        if current.kind == "anchor_registry":
            if not isinstance(next_content, AnchorRegistryContentV3):
                raise _error(
                    "agent_anchor_role_invalid",
                    "Authoritative Anchor Registry mutations require V3 content.",
                )
            for anchor in next_content.anchors:
                self._validate_v3_anchor_source(workflow_id, anchor)
        else:
            if not isinstance(next_content, StoryboardProductionPlanContentV3):
                raise _error(
                    "agent_storyboard_plan_invalid",
                    "Authoritative Storyboard mutations require V3 content.",
                )
            self._validate_v3_storyboard_content(workflow_id, next_content)
        request_digest = self._documents.digest_mutation(
            document_id=document_id,
            expected_revision=expected_revision,
            operation=operation,
            content=next_content,
            agent_run_id=agent_run_id,
        )
        return AgentDocumentMutationPlanV3(
            document_id=document_id,
            expected_revision=expected_revision,
            next_revision=expected_revision + 1,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            next_content=next_content,
        )

    def build_bounded_context(
        self,
        document_id: str,
        selector: str,
    ) -> AgentDocumentContextExcerptV2:
        document = self._documents.get(document_id)
        if document is None:
            raise _error(
                "agent_document_not_found",
                "Agent working document was not found.",
            )
        if document.kind == "anchor_registry":
            if not selector.startswith("anchors:"):
                raise _patch_error("Anchor context requires an anchors selector.")
            aliases = tuple(
                alias.strip()
                for alias in selector.removeprefix("anchors:").split(",")
                if alias.strip()
            )
            if not aliases:
                raise _patch_error("Anchor context selector is empty.")
            content = cast(AnchorRegistryContentV2, document.content)
            anchors_by_alias = {anchor.alias: anchor for anchor in content.anchors}
            if any(alias not in anchors_by_alias for alias in aliases):
                raise _patch_error("Anchor context selector is invalid.")
            excerpt = {
                "anchors": [anchors_by_alias[alias].model_dump(mode="json") for alias in aliases]
            }
        else:
            if not selector.startswith("sequence:"):
                raise _patch_error("Storyboard context requires a sequence selector.")
            sequence_id = selector.removeprefix("sequence:").strip()
            content = cast(StoryboardProductionPlanContentV2, document.content)
            segment = next(
                (item for item in content.segments if item.sequence_id == sequence_id),
                None,
            )
            if segment is None:
                raise _sequence_error("Storyboard context sequence was not found.")
            excerpt = {
                "global_parameters": content.global_parameters.model_dump(mode="json"),
                "segments": [segment.model_dump(mode="json")],
                "rows": [
                    row.model_dump(mode="json")
                    for row in content.rows
                    if row.sequence_id == sequence_id
                ],
                "node_records": [
                    record.model_dump(mode="json")
                    for record in content.node_records
                    if record.sequence_id in (None, sequence_id)
                ],
            }
        return AgentDocumentContextExcerptV2(
            document_id=document.document_id,
            document_kind=document.kind,
            revision=document.revision,
            content_digest=document.content_digest,
            selector=selector,
            content=excerpt,
        )

    def _require_scope(self, workflow_id: str, guidance_session_id: str) -> None:
        self._require_agent_canvas(workflow_id)
        session = self._conversations.get_guidance_session(workflow_id)
        if session.session_id != guidance_session_id:
            raise _error(
                "agent_document_cross_workflow_reference",
                "Guidance session does not belong to the workflow.",
            )

    def _require_agent_canvas(self, workflow_id: str) -> None:
        try:
            self._workflows.get_workflow(workflow_id)
        except V2PersistenceError as error:
            if error.code != "workflow_not_found":
                raise
            try:
                with self._workflows.database.engine.connect() as connection:
                    structured_workflow = connection.execute(
                        select(WorkflowRow.workflow_id).where(
                            WorkflowRow.workflow_id == workflow_id
                        )
                    ).scalar_one_or_none()
            except SQLAlchemyError as database_error:
                raise _error(
                    "agent_document_unavailable",
                    "Agent working document workflow validation failed.",
                ) from database_error
            if structured_workflow is not None:
                raise _error(
                    "workflow_not_agent_canvas",
                    "Workflow is not an Agent Canvas workflow.",
                ) from error
            raise

    def _apply_patch(
        self,
        current: AgentWorkingDocumentV2,
        patch: AgentDocumentPatchV2,
    ) -> AnchorRegistryContentV2 | StoryboardProductionPlanContentV2:
        if isinstance(patch, InitializeAnchorRegistryPatchV2):
            _require_kind(current, "anchor_registry")
            content = AnchorRegistryContentV2(anchors=patch.anchors)
            for anchor in content.anchors:
                self._validate_anchor_source(current.workflow_id, anchor)
            return content
        if isinstance(patch, UpsertAnchorPatchV2):
            _require_kind(current, "anchor_registry")
            content = cast(AnchorRegistryContentV2, current.content)
            self._validate_anchor_source(current.workflow_id, patch.anchor)
            anchors = list(content.anchors)
            existing_index = next(
                (
                    index
                    for index, anchor in enumerate(anchors)
                    if anchor.alias == patch.anchor.alias
                ),
                None,
            )
            if existing_index is None:
                anchors.append(patch.anchor)
            else:
                existing = anchors[existing_index]
                if existing.source_id is not None and (
                    patch.anchor.source_id != existing.source_id
                    or patch.anchor.source_kind != existing.source_kind
                ):
                    raise _error(
                        "agent_document_anchor_alias_conflict",
                        "An anchor alias cannot be rebound to another source.",
                    )
                anchors[existing_index] = patch.anchor
            return AnchorRegistryContentV2(anchors=tuple(anchors))
        if isinstance(patch, InitializeStoryboardPlanPatchV2):
            _require_kind(current, "storyboard_production_plan")
            self._validate_storyboard_content(
                current.workflow_id,
                current.guidance_session_id,
                patch.content,
            )
            return _with_computed_cursor(patch.content)

        _require_kind(current, "storyboard_production_plan")
        content = cast(StoryboardProductionPlanContentV2, current.content)
        if isinstance(patch, ReplaceNarrativeSegmentPatchV2):
            if patch.segment.sequence_id not in {
                segment.sequence_id for segment in content.segments
            }:
                raise _sequence_error("Storyboard sequence was not found.")
            segments = tuple(
                patch.segment if segment.sequence_id == patch.segment.sequence_id else segment
                for segment in content.segments
            )
            next_content = content.model_copy(update={"segments": segments})
        elif isinstance(patch, ReplaceStoryboardRowsPatchV2):
            if patch.sequence_id not in {segment.sequence_id for segment in content.segments}:
                raise _sequence_error("Storyboard sequence was not found.")
            if any(row.sequence_id != patch.sequence_id for row in patch.rows):
                raise _sequence_error("Storyboard rows do not match their sequence.")
            rows = tuple(
                row for row in content.rows if row.sequence_id != patch.sequence_id
            ) + tuple(patch.rows)
            rows = tuple(sorted(rows, key=lambda row: row.shot_index))
            next_content = content.model_copy(update={"rows": rows})
        elif isinstance(patch, MaterializeStoryboardSegmentPatchV2):
            from app.schemas.agent_canvas_storyboard_sequences import (
                StoryboardSegmentMaterializationDraftV2,
                StoryboardSequenceRowDraftV2,
            )
            from app.services.agent_canvas_storyboard_sequences import (
                StoryboardSequenceAuthoringService,
            )

            if any(row.sequence_id != patch.sequence_id for row in patch.rows):
                raise _sequence_error("Storyboard rows do not match their sequence.")
            next_content = StoryboardSequenceAuthoringService.materialize_segment_content(
                content,
                patch.sequence_id,
                StoryboardSegmentMaterializationDraftV2(
                    generation_prompt=patch.generation_prompt,
                    rows=tuple(
                        StoryboardSequenceRowDraftV2(
                            panel_index=row.panel_index,
                            content_beat=row.content_beat,
                            anchor_aliases=row.anchor_aliases,
                            camera_description=row.camera_description,
                        )
                        for row in patch.rows
                    ),
                ),
            )
        elif isinstance(patch, FreezeStoryboardVisualAnchorPatchV2):
            if content.visual_anchor is not None and content.visual_anchor != patch.visual_anchor:
                raise _sequence_error("Storyboard visual anchor is already frozen.")
            next_content = content.model_copy(update={"visual_anchor": patch.visual_anchor})
        elif isinstance(
            patch,
            (
                AttachStoryboardNodePatchV2,
                AttachVideoNodePatchV2,
                AttachAudioNodePatchV2,
                AttachEditingNodePatchV2,
            ),
        ):
            next_content = self._attach_node(current.workflow_id, content, patch)
        else:
            raise _patch_error("Agent document patch operation is unsupported.")
        validated = StoryboardProductionPlanContentV2.model_validate(
            next_content.model_dump(mode="json")
        )
        self._validate_storyboard_content(
            current.workflow_id,
            current.guidance_session_id,
            validated,
        )
        return _with_computed_cursor(validated)

    def _validate_anchor_source(self, workflow_id: str, anchor: AgentAnchorV2) -> None:
        if anchor.source_id is None:
            return
        if anchor.source_kind == "node":
            owner = self._node_owner(anchor.source_id)
            if owner is None:
                raise _error(
                    "agent_document_anchor_source_invalid",
                    "Anchor source Node was not found.",
                )
            if owner[0] != workflow_id:
                raise _cross_workflow_error()
            return
        if anchor.source_kind == "image_asset":
            version = self._assets.find_version(asset_id=anchor.source_id)
            if version is None or not version.mime_type.startswith("image/"):
                raise _error(
                    "agent_document_anchor_source_invalid",
                    "Anchor source must be an image Asset.",
                )
            if version.source_workflow_id != workflow_id:
                raise _cross_workflow_error()
            return
        try:
            snapshot = self._conversations.get_active_creative_direction_snapshot(workflow_id)
        except V2PersistenceError as error:
            raise _error(
                "agent_document_anchor_source_invalid",
                "Anchor source Style Skill Snapshot is not approved.",
            ) from error
        if snapshot.snapshot_id != anchor.source_id:
            try:
                candidate = self._conversations.get_creative_direction_snapshot(anchor.source_id)
            except V2PersistenceError as error:
                raise _error(
                    "agent_document_anchor_source_invalid",
                    "Anchor source Style Skill Snapshot was not found.",
                ) from error
            if candidate.workflow_id != workflow_id:
                raise _cross_workflow_error()
            raise _error(
                "agent_document_anchor_source_invalid",
                "Anchor source Style Skill Snapshot is not approved.",
            )

    def _validate_v3_anchor_source(self, workflow_id: str, anchor: AgentAnchorV3) -> None:
        source = anchor.source
        if isinstance(source, AgentAnchorNodeSourceV3):
            if source.workflow_id != workflow_id:
                raise _cross_workflow_error()
            node = self._workflows.get_node(workflow_id, source.node_id)
            if node.revision != source.node_revision:
                raise _error(
                    "agent_anchor_acceptance_stale",
                    "Anchor source Node revision is stale.",
                )
            expected_role = (
                "world_setting" if anchor.semantic_role == "world_setting" else anchor.semantic_role
            )
            if node.creative_role != expected_role:
                raise _error(
                    "agent_anchor_source_invalid",
                    "Anchor source Node does not match the semantic role.",
                )
            return
        if isinstance(source, AgentAnchorImageAssetVersionSourceV3):
            if source.workflow_id != workflow_id:
                raise _cross_workflow_error()
            node = self._workflows.get_node(workflow_id, source.node_id)
            if node.revision != source.node_revision:
                raise _error(
                    "agent_anchor_acceptance_stale",
                    "Anchor source Node revision is stale.",
                )
            version = self._assets.find_version(version_id=source.asset_version_id)
            if (
                version is None
                or version.asset_id != source.asset_id
                or version.source_workflow_id != workflow_id
                or version.source_node_id != source.node_id
                or version.status != "ready"
                or not version.mime_type.startswith("image/")
            ):
                raise _error(
                    "agent_anchor_source_invalid",
                    "Anchor activation requires the exact readable image Asset version.",
                )
            return
        if not isinstance(source, AgentAnchorSkillSnapshotSourceV3):
            raise _error("agent_anchor_source_invalid", "Anchor source is unsupported.")
        try:
            snapshot = self._conversations.get_active_creative_direction_snapshot(workflow_id)
        except V2PersistenceError as error:
            raise _error(
                "agent_anchor_source_invalid",
                "Anchor source Style Skill snapshot is not active.",
            ) from error
        if (
            snapshot.source_skill_id != source.skill_id
            or snapshot.source_skill_version != source.skill_version
            or snapshot.source_skill_digest != source.package_digest
        ):
            raise _error(
                "agent_anchor_source_invalid",
                "Anchor source Style Skill snapshot does not match the active selection.",
            )

    def _validate_v3_storyboard_content(
        self,
        workflow_id: str,
        content: StoryboardProductionPlanContentV3,
    ) -> None:
        for record in content.planned_nodes:
            node = self._workflows.get_node(workflow_id, record.node_id)
            if node.revision != record.node_revision:
                raise _error(
                    "agent_storyboard_plan_invalid",
                    "Storyboard planned Node revision is stale.",
                )
        if content.visual_anchor is not None:
            version = self._assets.find_version(version_id=content.visual_anchor.asset_version_id)
            if (
                version is None
                or version.asset_id != content.visual_anchor.asset_id
                or version.source_workflow_id != workflow_id
                or version.source_node_id != content.visual_anchor.node_id
                or version.status != "ready"
                or not version.mime_type.startswith("image/")
            ):
                raise _error(
                    "agent_storyboard_plan_invalid",
                    "Storyboard visual anchor requires the exact readable Grid Asset version.",
                )

    def _validate_storyboard_content(
        self,
        workflow_id: str,
        guidance_session_id: str,
        content: StoryboardProductionPlanContentV2,
    ) -> None:
        registry = self._documents.get_by_kind(
            workflow_id,
            guidance_session_id,
            "anchor_registry",
        )
        aliases = (
            {anchor.alias for anchor in cast(AnchorRegistryContentV2, registry.content).anchors}
            if registry is not None
            else set()
        )
        referenced_aliases = {alias for row in content.rows for alias in row.anchor_aliases}
        if not referenced_aliases <= aliases:
            raise _sequence_error("Storyboard rows reference unknown anchor aliases.")

    def _attach_node(
        self,
        workflow_id: str,
        content: StoryboardProductionPlanContentV2,
        patch: AttachStoryboardNodePatchV2
        | AttachVideoNodePatchV2
        | AttachAudioNodePatchV2
        | AttachEditingNodePatchV2,
    ) -> StoryboardProductionPlanContentV2:
        if isinstance(patch, AttachStoryboardNodePatchV2):
            role = "storyboard_grid"
            expected_type = "image"
            expected_creative_role = "storyboard_sequence"
            sequence_id: str | None = patch.sequence_id
        elif isinstance(patch, AttachVideoNodePatchV2):
            role = "video_segment"
            expected_type = "video"
            expected_creative_role = "storyboard_video"
            sequence_id = patch.sequence_id
        elif isinstance(patch, AttachAudioNodePatchV2):
            role = "bgm"
            expected_type = "audio"
            expected_creative_role = "bgm"
            sequence_id = None
        else:
            role = "editing"
            expected_type = "editing"
            expected_creative_role = "editing"
            sequence_id = None
        if sequence_id is not None and sequence_id not in {
            segment.sequence_id for segment in content.segments
        }:
            raise _sequence_error("Storyboard sequence was not found.")
        owner = self._node_owner(patch.node_id)
        if owner is None:
            raise _sequence_error("Storyboard linked Node was not found.")
        if owner[0] != workflow_id:
            raise _cross_workflow_error()
        if owner[1:] != (expected_type, expected_creative_role):
            raise _sequence_error("Storyboard linked Node has the wrong type.")
        record = StoryboardNodeRecordV2(
            sequence_id=sequence_id,
            node_role=role,
            node_id=patch.node_id,
        )
        records = tuple(
            item
            for item in content.node_records
            if (item.sequence_id, item.node_role) != (sequence_id, role)
        ) + (record,)
        return content.model_copy(update={"node_records": records})

    def _node_owner(self, node_id: str) -> tuple[str, str, str] | None:
        try:
            with self._workflows.database.engine.connect() as connection:
                row = connection.execute(
                    select(
                        AgentCanvasNodeRow.workflow_id,
                        AgentCanvasNodeRow.node_type,
                        AgentCanvasNodeRow.creative_role,
                    ).where(AgentCanvasNodeRow.node_id == node_id)
                ).one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "agent_document_unavailable",
                "Agent working document source validation failed.",
            ) from error
        if row is None:
            return None
        return str(row.workflow_id), str(row.node_type), str(row.creative_role)


def _with_computed_cursor(
    content: StoryboardProductionPlanContentV2,
) -> StoryboardProductionPlanContentV2:
    linked_sequences = {
        record.sequence_id
        for record in content.node_records
        if record.node_role == "storyboard_grid" and record.sequence_id is not None
    }
    contiguous_sequences = 0
    for segment in content.segments:
        if segment.sequence_id not in linked_sequences:
            break
        contiguous_sequences += 1
    return content.model_copy(update={"materialized_panel_cursor": contiguous_sequences * 9})


def _require_kind(
    document: AgentWorkingDocumentV2,
    expected_kind: str,
) -> None:
    if document.kind != expected_kind:
        raise _patch_error("Agent document patch does not match the document kind.")


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_working_documents")


def _patch_error(message: str) -> V2PersistenceError:
    return _error("agent_document_patch_invalid", message)


def _sequence_error(message: str) -> V2PersistenceError:
    return _error("agent_document_storyboard_sequence_invalid", message)


def _cross_workflow_error() -> V2PersistenceError:
    return _error(
        "agent_document_cross_workflow_reference",
        "Agent document source belongs to another workflow.",
    )
