"""Durable project-cover authority selection and historical backfill."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.project_repository import ProjectRepository
from app.schemas.v2_asset_library import AssetVersionMetadataV2
from app.schemas.workflow_v2_projects import ProjectCatalogRecord


class ProjectCoverBackfillDecision(BaseModel):
    """One deterministic, auditable project-cover decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    workflow_id: str
    outcome: str
    asset_id: str | None = None
    version_id: str | None = None
    candidate_count: int = 0


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
    ) -> None:
        if projects.database is not workflows.database:
            raise ValueError("Project cover repositories must share one V2Database.")
        self._projects = projects
        self._assets = assets
        self._workflows = workflows

    def consider_product_main(self, version: AssetVersionMetadataV2) -> bool:
        """Set automatic authority for one newly ready Product Main version."""

        if (
            not _eligible_media(version)
            or version.source_workflow_id is None
            or _semantic_role(version, {}) not in {"product_main", "product_main_image"}
        ):
            return False
        workflow = self._workflows.get_workflow(version.source_workflow_id)
        project = self._projects.get(workflow.project_id)
        if project.cover_state not in {"unresolved", "none", "broken"}:
            return False
        try:
            self._projects.update(
                project.project_id,
                expected_version=project.project_version,
                changes={
                    "cover_asset_id": version.asset_id,
                    "cover_version_id": version.version_id,
                    "cover_state": "ready",
                    "cover_source": "product_main",
                    "cover_updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except V2PersistenceError as error:
            if error.code == "project_state_conflict":
                return False
            raise
        return True

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
            decisions.append(decision)
            if not apply or decision.outcome not in {"ready", "none"}:
                continue
            now = datetime.now(timezone.utc).isoformat()
            changes: dict[str, object]
            if decision.outcome == "ready":
                changes = {
                    "cover_asset_id": decision.asset_id,
                    "cover_version_id": decision.version_id,
                    "cover_state": "ready",
                    "cover_source": "migrated",
                    "cover_updated_at": now,
                }
            else:
                changes = {
                    "cover_asset_id": None,
                    "cover_version_id": None,
                    "cover_state": "none",
                    "cover_source": "migrated",
                    "cover_updated_at": now,
                }
            try:
                self._projects.update(
                    project.project_id,
                    expected_version=project.project_version,
                    changes=changes,
                )
                updated += 1
            except V2PersistenceError as error:
                if error.code != "project_state_conflict":
                    raise
                conflicts += 1

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

    def _decide(self, project: ProjectCatalogRecord) -> ProjectCoverBackfillDecision:
        if project.cover_state in {"ready", "none"}:
            return ProjectCoverBackfillDecision(
                project_id=project.project_id,
                workflow_id=project.workflow_id,
                outcome="skipped",
            )

        versions = tuple(
            version
            for version in self._assets.list_versions_for_workflow(project.workflow_id)
            if _eligible_media(version)
        )
        if project.cover_asset_id is not None:
            existing = _latest_versions_by_asset(
                version for version in versions if version.asset_id == project.cover_asset_id
            )
            if len(existing) == 1:
                version = existing[0]
                return _ready_decision(project, version, candidate_count=1)

        workflow = self._workflows.get_workflow(project.workflow_id)
        node_roles: dict[str, str] = {}
        for node in workflow.nodes:
            role = _node_product_role(node)
            if role is not None:
                node_roles[node.node_id] = role
                if node.output_asset_id is not None:
                    node_roles[node.output_asset_id] = role
        candidates = _latest_versions_by_asset(
            version
            for version in versions
            if _semantic_role(version, node_roles) in {"product_main", "product_main_image"}
        )
        if not candidates:
            return ProjectCoverBackfillDecision(
                project_id=project.project_id,
                workflow_id=project.workflow_id,
                outcome="none" if not versions else "unresolved",
            )
        if len(candidates) > 1:
            return ProjectCoverBackfillDecision(
                project_id=project.project_id,
                workflow_id=project.workflow_id,
                outcome="ambiguous",
                candidate_count=len(candidates),
            )
        return _ready_decision(project, candidates[0], candidate_count=1)


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
    )


def _eligible_media(version: AssetVersionMetadataV2) -> bool:
    return version.status == "ready" and version.mime_type.startswith("image/")


def _semantic_role(
    version: AssetVersionMetadataV2,
    node_roles: dict[str, str],
) -> str | None:
    for key in ("source_semantic_role", "semantic_role", "semantic_type"):
        role = version.metadata.get(key)
        if isinstance(role, str) and role.strip():
            return role.strip()
    if version.source_node_id is not None and version.source_node_id in node_roles:
        return node_roles[version.source_node_id]
    return node_roles.get(version.asset_id)


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
