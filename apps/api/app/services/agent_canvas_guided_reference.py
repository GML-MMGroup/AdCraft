"""Typed guided reference-source validation and submission."""

from __future__ import annotations

from collections.abc import Callable

from app.persistence.agent_canvas_guided_reference_repository import (
    AgentCanvasGuidedReferenceRepository,
)
from app.persistence.agent_canvas_requirement_repository import AgentCanvasRequirementRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_guided_interactions import (
    GuidedInteractionAcceptedV1,
    GuidedInteractionV1,
    GuidedReferenceSourceSubmitV1,
    GuidedReferenceKindV1,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_requirements import character_occurrences_for_authoring


class GuidedReferenceSourceService:
    """Apply one typed Character/Scene Main reference choice."""

    def __init__(
        self,
        *,
        assets: AgentCanvasAssetService,
        asset_repository: V2AssetLibraryRepository,
        workflows: AgentCanvasWorkflowRepository,
        commits: AgentCanvasGuidedReferenceRepository,
    ) -> None:
        self._assets = assets
        self._asset_repository = asset_repository
        self._workflows = workflows
        self._commits = commits

    def set_continuation_writer(self, writer: Callable[..., None]) -> None:
        self._commits.set_continuation_writer(writer)

    def open_for_materialized_main(
        self,
        *,
        workflow_id: str,
        target_node_id: str,
        target_node_revision: int,
        reference_kind: GuidedReferenceKindV1,
        occurrence_id: str | None,
        source_turn_id: str,
    ) -> bool:
        """Open the optional reference wait for a newly published Main Draft."""

        if reference_kind == "character_main":
            requirement = AgentCanvasRequirementRepository(
                self._workflows.database
            ).get_current(workflow_id)
            occurrences = character_occurrences_for_authoring(requirement)
            if not occurrences:
                return False
            if occurrence_id not in {item.occurrence_id for item in occurrences}:
                raise V2PersistenceError(
                    "guided_reference_source_occurrence_mismatch",
                    "Reference source occurrence is not present in the Requirement Ledger.",
                    stage="guided_reference_service",
                )

        session = self._workflows.database
        with session.engine.connect() as connection:
            from sqlalchemy import select

            from app.persistence.models import AgentCanvasGuidanceSessionRow

            row = (
                connection.execute(
                    select(AgentCanvasGuidanceSessionRow).where(
                        AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise V2PersistenceError(
                "guidance_session_not_found",
                "Guidance session was not found.",
                stage="guided_reference_service",
            )
        self._commits.open_reference_source_with_journey(
            workflow_id,
            source_turn_id=source_turn_id,
            expected_session_revision=int(row["revision"]),
            idempotency_key=(
                f"open-reference:{workflow_id}:{target_node_id}:{target_node_revision}:"
                f"{reference_kind}:{occurrence_id or '-'}"
            ),
            reference_kind=reference_kind,
            target_node_id=target_node_id,
            target_node_revision=target_node_revision,
            occurrence_id=occurrence_id,
        )
        return True

    def submit_interaction(
        self,
        workflow_id: str,
        interaction: GuidedInteractionV1,
        request: GuidedReferenceSourceSubmitV1,
        *,
        submission_id: str,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1:
        """Validate the exact AssetVersion before the atomic authority commit."""

        sha256 = None
        if request.action == "use_reference":
            if request.asset_id is None or request.asset_version_id is None:
                raise V2PersistenceError(
                    "guided_reference_source_asset_required",
                    "A reference AssetVersion is required.",
                    stage="guided_reference_service",
                )
            version = self._asset_repository.find_version(
                asset_id=request.asset_id,
                version_id=request.asset_version_id,
            )
            if version is None:
                raise V2PersistenceError(
                    "guided_reference_source_asset_not_found",
                    "Reference AssetVersion was not found.",
                    stage="guided_reference_service",
                )
            if version.source_workflow_id != workflow_id:
                raise V2PersistenceError(
                    "guided_reference_source_asset_foreign_workflow",
                    "Reference AssetVersion is outside this Workflow.",
                    stage="guided_reference_service",
                )
            if version.status != "ready":
                raise V2PersistenceError(
                    "guided_reference_source_asset_unreadable",
                    "Reference AssetVersion is not readable.",
                    stage="guided_reference_service",
                )
            if version.mime_type.split("/", 1)[0] != "image":
                raise V2PersistenceError(
                    "guided_reference_source_asset_not_image",
                    "Reference AssetVersion must be an image.",
                    stage="guided_reference_service",
                )
            try:
                self._assets.resolve_asset_version_path(request.asset_id, request.asset_version_id)
            except V2PersistenceError as error:
                raise V2PersistenceError(
                    "guided_reference_source_asset_unreadable",
                    "Reference AssetVersion is not readable.",
                    stage="guided_reference_service",
                ) from error
            sha256 = version.sha256
        return self._commits.submit(
            workflow_id,
            interaction,
            request,
            submission_id=submission_id,
            idempotency_key=idempotency_key,
            asset_sha256=sha256,
        )
