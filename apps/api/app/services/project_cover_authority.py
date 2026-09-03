"""Durable project-cover authority selection and historical backfill."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.project_repository import ProjectRepository
from app.schemas.v2_asset_library import AssetVersionMetadataV2
from app.schemas.agent_canvas import AgentCanvasWorkflowV2
from app.schemas.workflow_v2_projects import ProjectCatalogRecord, ProjectCoverSourceV2
from app.services.project_cover_renditions import ProjectCoverRenditionPrewarmer


_SOURCE_PRIORITY: dict[ProjectCoverSourceV2, int] = {
    "product_main": 0,
    "scene_main": 1,
    "character_main": 2,
    "storyboard_grid": 3,
    "video_poster": 4,
    "manual": -1,
    "migrated": 5,
}


class ProjectCoverCandidate(BaseModel):
    """One immutable automatic cover candidate with a total deterministic rank."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str
    version_id: str
    source: ProjectCoverSourceV2
    source_priority: int
    business_index: int
    workflow_node_index: int

    @property
    def rank(self) -> tuple[int, int, int, str, str]:
        return (
            self.source_priority,
            self.business_index,
            self.workflow_node_index,
            self.asset_id,
            self.version_id,
        )


class ProjectCoverBackfillDecision(BaseModel):
    """One deterministic, auditable project-cover decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    workflow_id: str
    outcome: str
    source: ProjectCoverSourceV2 | None = None
    asset_id: str | None = None
    version_id: str | None = None
    candidate_count: int = 0
    reason: str
    changed: bool = False
    conflict: bool = False
    rendition_prewarm: str = "not_requested"


class ProjectCoverReconciliationResult(BaseModel):
    """Bounded live-publication result without exposing media or user content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal[
        "updated",
        "current",
        "lower_rank",
        "manual_protected",
        "ineligible",
        "conflict",
    ]
    changed: bool = False
    conflict: bool = False
    source: ProjectCoverSourceV2 | None = None
    asset_id: str | None = None
    version_id: str | None = None
    rendition_prewarm: str = "not_requested"


class ProjectCoverBackfillResult(BaseModel):
    """Aggregate dry-run or apply result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str
    scanned: int
    ready: int
    none: int
    unresolved: int
    ambiguous: int
    skipped: int
    conflicts: int
    updated: int
    decisions: tuple[ProjectCoverBackfillDecision, ...]


class ProjectCoverAuthorityService:
    """Resolve covers only from immutable workflow-owned semantic evidence."""

    def __init__(
        self,
        projects: ProjectRepository,
        assets: V2AssetLibraryRepository,
        workflows: AgentCanvasWorkflowRepository,
        prewarmer: ProjectCoverRenditionPrewarmer | None = None,
    ) -> None:
        if projects.database is not workflows.database:
            raise ValueError("Project cover repositories must share one V2Database.")
        self._projects = projects
        self._assets = assets
        self._workflows = workflows
        self._prewarmer = prewarmer

    def consider_published_version(
        self,
        version: AssetVersionMetadataV2,
    ) -> ProjectCoverReconciliationResult:
        """Converge one Project on the best currently published automatic cover."""

        if version.source_workflow_id is None:
            return ProjectCoverReconciliationResult(disposition="ineligible")
        workflow = self._workflows.get_workflow(version.source_workflow_id)
        project = self._projects.get(workflow.project_id)
        if project.cover_source == "manual":
            return ProjectCoverReconciliationResult(disposition="manual_protected")
        versions = self._assets.list_versions_for_workflow(workflow.workflow_id)
        selected = _select_automatic_cover(workflow, versions)
        if selected is None:
            return ProjectCoverReconciliationResult(disposition="ineligible")
        current = _candidate_for_identity(
            workflow,
            versions,
            asset_id=project.cover_asset_id,
            version_id=project.cover_version_id,
        )
        if current is not None and selected.rank >= current.rank:
            prewarm = "not_requested"
            if selected.version_id == current.version_id:
                prewarm = self._prewarm(_version_by_id(versions, current.version_id))
            return ProjectCoverReconciliationResult(
                disposition=(
                    "current" if selected.version_id == current.version_id else "lower_rank"
                ),
                source=current.source,
                asset_id=current.asset_id,
                version_id=current.version_id,
                rendition_prewarm=prewarm,
            )
        if (
            project.cover_state == "ready"
            and project.cover_asset_id == selected.asset_id
            and project.cover_version_id == selected.version_id
            and project.cover_source == selected.source
        ):
            return ProjectCoverReconciliationResult(
                disposition="current",
                source=selected.source,
                asset_id=selected.asset_id,
                version_id=selected.version_id,
            )
        try:
            self._projects.update(
                project.project_id,
                expected_version=project.project_version,
                changes={
                    "cover_asset_id": selected.asset_id,
                    "cover_version_id": selected.version_id,
                    "cover_state": "ready",
                    "cover_source": selected.source,
                    "cover_updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except V2PersistenceError as error:
            if error.code == "project_state_conflict":
                return ProjectCoverReconciliationResult(
                    disposition="conflict",
                    conflict=True,
                    source=selected.source,
                    asset_id=selected.asset_id,
                    version_id=selected.version_id,
                )
            raise
        prewarm = self._prewarm(_version_by_id(versions, selected.version_id))
        return ProjectCoverReconciliationResult(
            disposition="updated",
            changed=True,
            source=selected.source,
            asset_id=selected.asset_id,
            version_id=selected.version_id,
            rendition_prewarm=prewarm,
        )

    def consider_product_main(self, version: AssetVersionMetadataV2) -> bool:
        """Compatibility wrapper for the former Product-only callback."""

        return self.consider_published_version(version).changed

    def backfill(
        self,
        *,
        apply: bool = False,
        max_projects: int | None = None,
    ) -> ProjectCoverBackfillResult:
        """Plan or apply a stable, idempotent historical cover backfill."""

        projects = self._catalog_snapshot(max_projects=max_projects)
        decisions: list[ProjectCoverBackfillDecision] = []
        updated = 0
        conflicts = 0
        for project in projects:
            decision = self._decide(project)
            if not apply or not decision.changed:
                decisions.append(decision)
                continue
            now = datetime.now(timezone.utc).isoformat()
            changes: dict[str, object]
            if decision.outcome == "ready":
                changes = {
                    "cover_asset_id": decision.asset_id,
                    "cover_version_id": decision.version_id,
                    "cover_state": "ready",
                    "cover_source": decision.source,
                    "cover_updated_at": now,
                }
            else:
                changes = {
                    "cover_asset_id": None,
                    "cover_version_id": None,
                    "cover_state": "none",
                    "cover_source": None,
                    "cover_updated_at": now,
                }
            try:
                self._projects.update(
                    project.project_id,
                    expected_version=project.project_version,
                    changes=changes,
                )
                updated += 1
                if decision.version_id is not None:
                    disposition = self._prewarm(
                        _version_by_id(
                            self._assets.list_versions_for_workflow(project.workflow_id),
                            decision.version_id,
                        )
                    )
                    decision = decision.model_copy(update={"rendition_prewarm": disposition})
            except V2PersistenceError as error:
                if error.code != "project_state_conflict":
                    raise
                conflicts += 1
                decision = decision.model_copy(
                    update={"changed": False, "conflict": True, "reason": "project_cas_conflict"}
                )
            decisions.append(decision)

        return ProjectCoverBackfillResult(
            mode="apply" if apply else "dry-run",
            scanned=len(projects),
            ready=sum(item.outcome == "ready" for item in decisions),
            none=sum(item.outcome == "none" for item in decisions),
            unresolved=sum(item.outcome == "unresolved" for item in decisions),
            ambiguous=sum(item.outcome == "ambiguous" for item in decisions),
            skipped=sum(item.outcome == "skipped" for item in decisions),
            conflicts=conflicts,
            updated=updated,
            decisions=tuple(decisions),
        )

    def _catalog_snapshot(
        self,
        *,
        max_projects: int | None,
    ) -> tuple[ProjectCatalogRecord, ...]:
        items: list[ProjectCatalogRecord] = []
        for status in ("active", "archived", "trashed"):
            cursor = None
            while max_projects is None or len(items) < max_projects:
                remaining = 100 if max_projects is None else min(100, max_projects - len(items))
                if remaining <= 0:
                    break
                page = self._projects.list_catalog(
                    status=status,
                    limit=remaining,
                    cursor=cursor,
                )
                items.extend(page.items)
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
        return tuple(items)

    def _prewarm(self, version: AssetVersionMetadataV2 | None) -> str:
        if self._prewarmer is None or version is None:
            return "not_configured"
        try:
            return self._prewarmer.ensure(version)
        except V2PersistenceError:
            return "failed"

    def _decide(self, project: ProjectCatalogRecord) -> ProjectCoverBackfillDecision:
        if project.cover_source == "manual":
            return ProjectCoverBackfillDecision(
                project_id=project.project_id,
                workflow_id=project.workflow_id,
                outcome="skipped",
                reason="manual_protected",
            )

        versions = tuple(
            version
            for version in self._assets.list_versions_for_workflow(project.workflow_id)
            if _eligible_media(version)
        )
        workflow = self._workflows.get_workflow(project.workflow_id)
        candidates = tuple(
            candidate
            for version in versions
            if (candidate := _candidate_for_version(workflow, version)) is not None
        )
        selected = min(candidates, key=lambda item: item.rank, default=None)
        if selected is None:
            outcome = "none" if not versions else "unresolved"
            changed = outcome == "none" and (
                project.cover_state != "none"
                or project.cover_source is not None
                or project.cover_asset_id is not None
                or project.cover_version_id is not None
            )
            return ProjectCoverBackfillDecision(
                project_id=project.project_id,
                workflow_id=project.workflow_id,
                outcome=outcome,
                candidate_count=0,
                reason="no_candidate" if not versions else "unclassified_evidence",
                changed=changed,
            )
        current = _candidate_for_identity(
            workflow,
            versions,
            asset_id=project.cover_asset_id,
            version_id=project.cover_version_id,
        )
        if (
            current is not None
            and selected.rank >= current.rank
            and project.cover_state == "ready"
            and project.cover_source == current.source
        ):
            return ProjectCoverBackfillDecision(
                project_id=project.project_id,
                workflow_id=project.workflow_id,
                outcome="skipped",
                source=current.source,
                asset_id=current.asset_id,
                version_id=current.version_id,
                candidate_count=len(candidates),
                reason="automatic_cover_current",
            )
        return ProjectCoverBackfillDecision(
            project_id=project.project_id,
            workflow_id=project.workflow_id,
            outcome="ready",
            source=selected.source,
            asset_id=selected.asset_id,
            version_id=selected.version_id,
            candidate_count=len(candidates),
            reason=(
                "migrated_source_normalized"
                if current is not None and project.cover_source == "migrated"
                else "better_automatic_candidate"
            ),
            changed=True,
        )


def _ready_decision(
    project: ProjectCatalogRecord,
    version: AssetVersionMetadataV2,
    *,
    candidate_count: int,
) -> ProjectCoverBackfillDecision:
    return ProjectCoverBackfillDecision(
        project_id=project.project_id,
        workflow_id=project.workflow_id,
        outcome="ready",
        asset_id=version.asset_id,
        version_id=version.version_id,
        candidate_count=candidate_count,
        reason="legacy_exact_identity",
    )


def _select_automatic_cover(
    workflow: AgentCanvasWorkflowV2,
    versions: Iterable[AssetVersionMetadataV2],
) -> ProjectCoverCandidate | None:
    """Select one cover from canonical metadata without reading mutable external state."""

    candidates = tuple(
        candidate
        for version in versions
        if (candidate := _candidate_for_version(workflow, version)) is not None
    )
    return min(candidates, key=lambda item: item.rank, default=None)


def _candidate_for_identity(
    workflow: AgentCanvasWorkflowV2,
    versions: Iterable[AssetVersionMetadataV2],
    *,
    asset_id: str | None,
    version_id: str | None,
) -> ProjectCoverCandidate | None:
    if asset_id is None or version_id is None:
        return None
    for version in versions:
        if version.asset_id == asset_id and version.version_id == version_id:
            return _candidate_for_version(workflow, version)
    return None


def _candidate_for_version(
    workflow: AgentCanvasWorkflowV2,
    version: AssetVersionMetadataV2,
) -> ProjectCoverCandidate | None:
    if version.status != "ready" or version.source_workflow_id != workflow.workflow_id:
        return None
    node_indexes: dict[str, int] = {}
    node_roles: dict[str, str] = {}
    nodes_by_identity: dict[str, object] = {}
    for index, node in enumerate(workflow.nodes):
        node_indexes[node.node_id] = index
        nodes_by_identity[node.node_id] = node
        if node.output_asset_id is not None:
            node_indexes[node.output_asset_id] = index
            nodes_by_identity[node.output_asset_id] = node
        role = _node_cover_role(node)
        if role is not None:
            node_roles[node.node_id] = role
            if node.output_asset_id is not None:
                node_roles[node.output_asset_id] = role
    node = nodes_by_identity.get(version.source_node_id or "")
    if node is None:
        node = nodes_by_identity.get(version.asset_id)
    if version.source_node_id is not None and node is None:
        return None
    role = _resolved_cover_source(version, node_roles)
    if role is None:
        return None
    node_role = _canonical_cover_source(node_roles.get(version.source_node_id or ""))
    if node_role is not None and node_role != role:
        return None
    output_asset_id = getattr(node, "output_asset_id", None)
    if output_asset_id is not None and output_asset_id != version.asset_id:
        return None
    if role == "video_poster":
        if not version.mime_type.startswith("video/"):
            return None
    elif not version.mime_type.startswith("image/"):
        return None
    business_index = 0
    if role == "character_main":
        business_index = _consistent_index(version, node, "occurrence_index")
        if business_index is None:
            return None
    elif role in {"storyboard_grid", "video_poster"}:
        business_index = _consistent_index(version, node, "sequence_index")
        if business_index is None:
            return None
    workflow_node_index = node_indexes.get(version.source_node_id or "")
    if workflow_node_index is None:
        workflow_node_index = version.metadata.get("workflow_node_index", len(workflow.nodes))
    if (
        not isinstance(workflow_node_index, int)
        or isinstance(workflow_node_index, bool)
        or workflow_node_index < 0
    ):
        return None
    return ProjectCoverCandidate(
        asset_id=version.asset_id,
        version_id=version.version_id,
        source=role,
        source_priority=_SOURCE_PRIORITY[role],
        business_index=business_index,
        workflow_node_index=workflow_node_index,
    )


def _canonical_cover_source(role: str | None) -> ProjectCoverSourceV2 | None:
    aliases: dict[str, ProjectCoverSourceV2] = {
        "product_main": "product_main",
        "product_main_image": "product_main",
        "scene_main": "scene_main",
        "scene_main_image": "scene_main",
        "scene_board": "scene_main",
        "character_main": "character_main",
        "character_main_image": "character_main",
        "storyboard_grid": "storyboard_grid",
        "video_segment": "video_poster",
        "video_poster": "video_poster",
    }
    return aliases.get(role or "")


def _resolved_cover_source(
    version: AssetVersionMetadataV2,
    node_roles: dict[str, str],
) -> ProjectCoverSourceV2 | None:
    version_role = _semantic_role(version)
    specific_version_role = _canonical_cover_source(version_role)
    node_role = _canonical_cover_source(
        node_roles.get(version.source_node_id or "") or node_roles.get(version.asset_id)
    )
    if specific_version_role is not None:
        if node_role is not None and node_role != specific_version_role:
            return None
        return specific_version_role
    generic_roles: dict[str, ProjectCoverSourceV2] = {
        "product": "product_main",
        "scene": "scene_main",
        "character": "character_main",
        "storyboard_sequence": "storyboard_grid",
        "storyboard_video": "video_poster",
    }
    if version_role is not None and generic_roles.get(version_role) != node_role:
        return None
    return node_role


def _consistent_index(
    version: AssetVersionMetadataV2,
    node: object | None,
    key: str,
) -> int | None:
    values = [version.metadata.get(key)]
    node_metadata = getattr(node, "metadata", None)
    if isinstance(node_metadata, dict):
        values.append(node_metadata.get(key))
    present = [value for value in values if value is not None]
    if not present:
        return None
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in present):
        return None
    if len(set(present)) != 1:
        return None
    return present[0]


def _eligible_media(version: AssetVersionMetadataV2) -> bool:
    return version.status == "ready" and (
        version.mime_type.startswith("image/") or version.mime_type.startswith("video/")
    )


def _semantic_role(
    version: AssetVersionMetadataV2,
) -> str | None:
    for key in ("source_semantic_role", "semantic_role", "semantic_type"):
        role = version.metadata.get(key)
        if isinstance(role, str) and role.strip():
            return role.strip()
    return None


def _node_product_role(node) -> str | None:
    """Return Product Main only from canonical node metadata, never display text."""

    prompt_recipe_id = node.metadata.get("prompt_recipe_id")
    if prompt_recipe_id == "adcraft.agent_canvas.product_main":
        return "product_main"
    if (
        node.semantic_role == "product"
        and node.metadata.get("source_input_kind") == "main"
        and isinstance(node.metadata.get("provenance"), dict)
        and node.metadata["provenance"].get("kind") == "direct_upload"
    ):
        return "product_main"
    return None


def _node_cover_role(node) -> str | None:
    roles: set[str] = set()
    product_role = _node_product_role(node)
    if product_role is not None:
        roles.add(product_role)
    recipe = node.metadata.get("prompt_recipe_id")
    recipes = {
        "adcraft.agent_canvas.product_main": "product_main",
        "adcraft.agent_canvas.scene_board": "scene_main",
        "adcraft.agent_canvas.character_main": "character_main",
        "adcraft.agent_canvas.storyboard_grid": "storyboard_grid",
        "adcraft.agent_canvas.video_segment": "video_poster",
    }
    if isinstance(recipe, str) and recipe in recipes:
        roles.add(recipes[recipe])
    structured_content = getattr(node, "structured_content", {})
    creative_role = getattr(node, "creative_role", getattr(node, "semantic_role", None))
    if creative_role == "product" and structured_content.get("asset_kind") == "main":
        roles.add("product_main")
    if (
        creative_role == "character"
        and structured_content.get("character_asset_kind") == "identity_master"
    ):
        roles.add("character_main")
    if creative_role == "scene":
        roles.add("scene_main")
    if creative_role == "storyboard_sequence":
        roles.add("storyboard_grid")
    if creative_role == "storyboard_video":
        roles.add("video_poster")
    return next(iter(roles)) if len(roles) == 1 else None


def _latest_versions_by_asset(
    versions: Iterable[AssetVersionMetadataV2],
) -> tuple[AssetVersionMetadataV2, ...]:
    latest: dict[str, AssetVersionMetadataV2] = {}
    for version in versions:
        current = latest.get(version.asset_id)
        if current is None or (version.version_no, version.version_id) > (
            current.version_no,
            current.version_id,
        ):
            latest[version.asset_id] = version
    return tuple(latest[asset_id] for asset_id in sorted(latest))


def _version_by_id(
    versions: Iterable[AssetVersionMetadataV2], version_id: str
) -> AssetVersionMetadataV2 | None:
    return next((version for version in versions if version.version_id == version_id), None)
