"""Read-only role-filtered candidates for the guided reference interaction."""

from __future__ import annotations

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_guided_references import (
    ReferenceCandidateKindV2,
    ReferenceCandidateListResponseV2,
    ReferenceCandidateScopeV2,
    ReferenceCandidateV2,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService


class GuidedReferenceCandidateService:
    """Project a bounded, exact-version candidate list without mutating state."""

    def __init__(
        self,
        *,
        assets: AgentCanvasAssetService,
        workflows: AgentCanvasWorkflowRepository,
    ) -> None:
        self._assets = assets
        self._workflows = workflows

    def list(
        self,
        workflow_id: str,
        *,
        reference_kind: ReferenceCandidateKindV2,
        scope: ReferenceCandidateScopeV2,
        cursor: str | None = None,
        query: str | None = None,
    ) -> ReferenceCandidateListResponseV2:
        try:
            self._workflows.get_workflow(workflow_id)
        except V2PersistenceError as error:
            if error.code == "workflow_not_found":
                raise
            raise V2PersistenceError(
                "reference_candidates_unavailable",
                "Reference candidates are unavailable.",
                stage="guided_reference_candidates",
            ) from error
        offset = _cursor_offset(cursor)
        normalized_query = query.strip().casefold() if query else None
        candidates = (
            self._project_candidates(workflow_id, reference_kind)
            if scope == "project"
            else self._library_candidates(reference_kind, scope)
        )
        if normalized_query:
            candidates = tuple(
                item for item in candidates if normalized_query in item.display_name.casefold()
            )
        page = candidates[offset : offset + 100]
        next_cursor = str(offset + 100) if offset + 100 < len(candidates) else None
        return ReferenceCandidateListResponseV2(
            workflow_id=workflow_id,
            reference_kind=reference_kind,
            scope=scope,
            items=page,
            next_cursor=next_cursor,
        )

    def _project_candidates(
        self, workflow_id: str, reference_kind: ReferenceCandidateKindV2
    ) -> tuple[ReferenceCandidateV2, ...]:
        expected_role = _semantic_role(reference_kind)
        expected_purpose = _reference_purpose(reference_kind)
        result: list[ReferenceCandidateV2] = []
        for asset in self._assets.list_project_assets(workflow_id):
            if asset.status != "ready" or asset.media_type != "image" or not asset.version_id:
                continue
            if not _project_role_matches(asset.source_semantic_role, reference_kind):
                continue
            result.append(
                _candidate(
                    asset_id=asset.asset_id,
                    version_id=asset.version_id,
                    display_name=asset.display_name,
                    reference_kind=reference_kind,
                    semantic_role=expected_role,
                    purpose=expected_purpose,
                )
            )
        return tuple(result)

    def _library_candidates(
        self,
        reference_kind: ReferenceCandidateKindV2,
        scope: ReferenceCandidateScopeV2,
    ) -> tuple[ReferenceCandidateV2, ...]:
        expected_role = _semantic_role(reference_kind)
        expected_purpose = _reference_purpose(reference_kind)
        expected_semantic_type = (
            "character_three_view"
            if reference_kind == "character_main"
            else "scene_multi_view_grid"
        )
        result: list[ReferenceCandidateV2] = []
        for entity in self._assets.list_images(scope=scope):
            member = entity.preview_member
            if member is None or member.semantic_type != expected_semantic_type:
                continue
            result.append(
                _candidate(
                    entity_id=entity.entity_id,
                    member_id=member.member_id,
                    asset_id=member.asset_id,
                    version_id=member.version_id,
                    display_name=entity.display_name,
                    reference_kind=reference_kind,
                    semantic_role=expected_role,
                    purpose=expected_purpose,
                )
            )
        return tuple(result)


def _cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as error:
        raise V2PersistenceError(
            "reference_candidates_unavailable",
            "Reference candidate cursor is invalid.",
            stage="guided_reference_candidates",
        ) from error
    if offset < 0 or offset > 10_000:
        raise V2PersistenceError(
            "reference_candidates_unavailable",
            "Reference candidate cursor is invalid.",
            stage="guided_reference_candidates",
        )
    return offset


def _semantic_role(reference_kind: ReferenceCandidateKindV2) -> str:
    return "character_reference" if reference_kind == "character_main" else "scene_reference"


def _reference_purpose(reference_kind: ReferenceCandidateKindV2) -> str:
    return "identity_guidance" if reference_kind == "character_main" else "environment_guidance"


def _project_role_matches(role: str | None, reference_kind: ReferenceCandidateKindV2) -> bool:
    if role is None:
        return False
    accepted = (
        {"character_reference", "character_main", "character"}
        if reference_kind == "character_main"
        else {"scene_reference", "scene_main", "scene"}
    )
    return role in accepted


def _candidate(
    *,
    asset_id: str,
    version_id: str,
    display_name: str,
    reference_kind: ReferenceCandidateKindV2,
    semantic_role: str,
    purpose: str,
    entity_id: str | None = None,
    member_id: str | None = None,
) -> ReferenceCandidateV2:
    return ReferenceCandidateV2(
        entity_id=entity_id,
        member_id=member_id,
        asset_id=asset_id,
        asset_version_id=version_id,
        media_type="image",
        display_name=display_name,
        preview_url=f"/api/v2/assets/{asset_id}/preview?v={version_id}",
        content_url=f"/api/v2/assets/{asset_id}/content?v={version_id}",
        reference_kind=reference_kind,
        semantic_reference_role=semantic_role,  # type: ignore[arg-type]
        reference_purpose=purpose,  # type: ignore[arg-type]
        selectable=True,
    )
