"""Atomic, reference-aware deletion of one trashed Project and its owned records."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy import Table, case, delete, func, insert, or_, select, tuple_, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import ColumnElement

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import (
    AgentCanvasIdempotencyRow,
    AgentCanvasWorkflowRow,
    AssetRow,
    AssetVersionRow,
    Base,
    BrandRow,
    ProjectDeletionReceiptRow,
    ProjectRow,
)
from app.schemas.project_deletion import ProjectDeletionManifestV1


_RECEIPTS = ProjectDeletionReceiptRow.__table__
_BUSY = {
    "agent_canvas_executions": ("queued", "running", "waiting"),
    "agent_canvas_editing_exports": ("queued", "exporting"),
    "agent_runs": ("running",),
    "agent_canvas_provider_tasks": ("submitted", "waiting", "recovering"),
    "agent_canvas_provider_submission_intents": ("submitted", "outcome_unknown"),
    "agent_canvas_continuation_outbox": ("leased",),
    "agent_canvas_prompt_preparation_outbox": ("leased",),
    "agent_canvas_automatic_run_commands": ("claimed",),
    "agent_canvas_guided_media_resume_deliveries": ("running",),
    "agent_canvas_post_ready_effects": ("running",),
    "agent_canvas_chat_turns": ("running",),
    "brand_continuations": ("running",),
}


class ProjectDeletionRepository:
    def __init__(self, database: V2Database) -> None:
        self.database = database

    def delete(self, project_id: str, *, expected_version: int) -> ProjectDeletionManifestV1:
        with self.database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                receipt = (
                    connection.execute(
                        select(_RECEIPTS).where(_RECEIPTS.c.project_id == project_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                if receipt is not None:
                    _require_version(receipt["project_version"], expected_version)
                    connection.commit()
                    return ProjectDeletionManifestV1.model_validate_json(receipt["manifest_json"])
                project = (
                    connection.execute(
                        select(ProjectRow.__table__).where(ProjectRow.project_id == project_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                if project is None:
                    raise _error("project_not_found", "Project was not found.")
                _require_version(project["project_version"], expected_version)
                if project["status"] != "trashed":
                    raise _error(
                        "project_not_trashed", "Only trashed projects can be permanently deleted."
                    )
                workflow_ids = tuple(
                    connection.execute(
                        select(AgentCanvasWorkflowRow.workflow_id).where(
                            AgentCanvasWorkflowRow.project_id == project_id
                        )
                    ).scalars()
                )
                if not workflow_ids:
                    raise _error(
                        "workflow_not_agent_canvas",
                        "Project does not own an Agent Canvas workflow.",
                    )
                predicates = _owned_predicates(connection, project_id, workflow_ids)
                _require_idle(connection, predicates)
                # A retained asset may outlive its original Project. Include
                # prior deletion authority when its last consumer disappears.
                deleted_workflows = set(_deleted_workflow_owners(connection)) | set(workflow_ids)
                candidates = _owned_assets(connection, tuple(deleted_workflows))
                # Failed publication can leave verified bytes without a registered
                # AssetVersion. Preserve their durable cleanup identity first.
                unpublished_keys = _owned_object_keys(connection, predicates)
                # Snapshot keys before deletion: child queries must not depend on a
                # parent that has already been removed. Deferred FKs handle cycles.
                plan = [
                    (
                        table,
                        tuple(
                            connection.execute(
                                select(*table.primary_key.columns).where(predicate)
                            ).all()
                        ),
                    )
                    for table, predicate in predicates.items()
                ]
                connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
                for table, keys in reversed(plan):
                    _delete_keys(connection, table, keys)
                _delete_idempotency_payloads(connection, project_id, workflow_ids)
                retained = referenced_asset_ids(connection, candidates)
                removable = candidates - retained
                objects = _asset_objects(connection, removable)
                storage_keys = {key for keys in objects.values() for key in keys} | unpublished_keys
                _remove_assets(connection, removable)
                manifest = ProjectDeletionManifestV1(
                    project_id=project_id,
                    workflow_ids=workflow_ids,
                    asset_ids=tuple(sorted(removable)),
                    storage_keys=tuple(sorted(storage_keys)),
                )
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    insert(_RECEIPTS).values(
                        project_id=project_id,
                        project_version=expected_version,
                        manifest_json=manifest.model_dump_json(),
                        cleanup_completed=False,
                        created_at=now,
                        updated_at=now,
                    )
                )
                connection.commit()
                return manifest
            except SQLAlchemyError as error:
                connection.rollback()
                raise _error(
                    "project_deletion_failed",
                    "Project deletion failed. No project records were removed.",
                ) from error
            except BaseException:
                connection.rollback()
                raise

    def reclaim_unreferenced_assets(self) -> None:
        """Reclaim only assets backed by prior permanent-deletion authority."""
        with self.database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                owners = _deleted_workflow_owners(connection)
                if not owners:
                    connection.commit()
                    return
                candidates = _owned_assets(connection, tuple(owners))
                removable = candidates - referenced_asset_ids(connection, candidates)
                if not removable:
                    connection.commit()
                    return
                objects = _asset_objects(connection, removable)
                groups: dict[str, set[str]] = {}
                # Each logical asset is charged to one existing deletion receipt,
                # even if its versions originated in several deleted workflows.
                asset_owners: dict[str, str] = {}
                for batch in _batches(sorted(removable)):
                    for asset_id, workflow_id in connection.execute(
                        select(
                            AssetVersionRow.asset_id,
                            AssetVersionRow.source_workflow_id,
                        ).where(AssetVersionRow.asset_id.in_(batch))
                    ):
                        project_id = owners[workflow_id]
                        asset_owners[asset_id] = min(
                            asset_owners.get(asset_id, project_id), project_id
                        )
                for asset_id, project_id in asset_owners.items():
                    groups.setdefault(project_id, set()).add(asset_id)
                connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
                _remove_assets(connection, removable)
                for project_id, assets in groups.items():
                    manifest = ProjectDeletionManifestV1.model_validate_json(
                        connection.execute(
                            select(_RECEIPTS.c.manifest_json).where(
                                _RECEIPTS.c.project_id == project_id
                            )
                        ).scalar_one()
                    )
                    keys = {key for asset in assets for key in objects[asset]}
                    expanded = manifest.model_copy(
                        update={
                            "asset_ids": tuple(sorted(set(manifest.asset_ids) | assets)),
                            "storage_keys": tuple(sorted(set(manifest.storage_keys) | keys)),
                        }
                    )
                    connection.execute(
                        update(_RECEIPTS)
                        .where(_RECEIPTS.c.project_id == project_id)
                        .values(
                            manifest_json=expanded.model_dump_json(),
                            cleanup_completed=False,
                        )
                    )
                connection.commit()
            except SQLAlchemyError as error:
                connection.rollback()
                raise _error(
                    "project_reclamation_failed", "Unused project media could not be reclaimed."
                ) from error
            except BaseException:
                connection.rollback()
                raise

    def cleanup_candidates(self, limit: int = 20) -> tuple[ProjectDeletionManifestV1, ...]:
        """Fairly revisit receipts, including historical completed cleanups."""
        with self.database.engine.connect() as connection:
            return tuple(
                ProjectDeletionManifestV1.model_validate_json(value)
                for value in connection.execute(
                    select(_RECEIPTS.c.manifest_json)
                    .order_by(_RECEIPTS.c.updated_at, _RECEIPTS.c.project_id)
                    .limit(limit)
                ).scalars()
            )

    def record_cleanup(self, manifest: ProjectDeletionManifestV1, *, completed: bool) -> bool:
        with self.database.engine.begin() as connection:
            result = connection.execute(
                update(_RECEIPTS)
                .where(
                    _RECEIPTS.c.project_id == manifest.project_id,
                    _RECEIPTS.c.manifest_json == manifest.model_dump_json(),
                )
                .values(
                    cleanup_completed=completed, updated_at=datetime.now(timezone.utc).isoformat()
                )
            )
            return result.rowcount == 1


def _deleted_workflow_owners(connection: Connection) -> dict[str, str]:
    workflows = func.json_each(_RECEIPTS.c.manifest_json, "$.workflow_ids").table_valued(
        "value",
        joins_implicitly=True,
    )
    return dict(
        connection.execute(
            select(workflows.c.value, _RECEIPTS.c.project_id).select_from(_RECEIPTS, workflows)
        ).all()
    )


def _asset_objects(connection: Connection, assets: set[str]) -> dict[str, set[str]]:
    objects: dict[str, set[str]] = {asset: set() for asset in assets}
    for batch in _batches(sorted(assets)):
        for asset_id, key, metadata_json in connection.execute(
            select(
                AssetVersionRow.asset_id,
                AssetVersionRow.storage_key,
                AssetVersionRow.metadata_json,
            ).where(AssetVersionRow.asset_id.in_(batch))
        ):
            objects[asset_id].add(key)
            metadata = json.loads(metadata_json)
            for field in ("preview_storage_key", "poster_storage_key"):
                value = metadata.get(field)
                if isinstance(value, str):
                    objects[asset_id].add(value)
    return objects


def _owned_object_keys(
    connection: Connection, predicates: dict[Table, ColumnElement[bool]]
) -> set[str]:
    keys: set[str] = set()
    for table, predicate in predicates.items():
        for column in table.c:
            if column.name.endswith("storage_key"):
                keys.update(
                    value
                    for value in connection.execute(
                        select(column).where(predicate, column.is_not(None))
                    ).scalars()
                    if value.startswith("assets/objects/sha256/")
                )
    return keys


def _remove_assets(connection: Connection, assets: set[str]) -> None:
    for batch in _batches(sorted(assets)):
        connection.execute(delete(AssetVersionRow).where(AssetVersionRow.asset_id.in_(batch)))
        connection.execute(delete(AssetRow).where(AssetRow.asset_id.in_(batch)))


def _owned_predicates(
    connection: Connection, project_id: str, workflow_ids: tuple[str, ...]
) -> dict[Table, ColumnElement[bool]]:
    brands = tuple(
        connection.execute(
            select(BrandRow.brand_id).where(BrandRow.project_id == project_id)
        ).scalars()
    )
    predicates: dict[Table, ColumnElement[bool]] = {}
    tables = tuple(table for table in Base.metadata.tables.values() if table is not _RECEIPTS)
    for table in tables:
        conditions = []
        if "project_id" in table.c:
            conditions.append(table.c.project_id == project_id)
        if "workflow_id" in table.c:
            conditions.append(table.c.workflow_id.in_(workflow_ids))
        if "brand_id" in table.c and brands:
            conditions.append(table.c.brand_id.in_(brands))
        if conditions:
            predicates[table] = or_(*conditions)
    # Descendants without a direct owner (document revisions, option rows,
    # stream chunks, etc.) inherit scope only through declared foreign keys.
    while True:
        additions = {}
        for table in tables:
            if table in predicates:
                continue
            conditions = []
            for constraint in table.foreign_key_constraints:
                parent = constraint.referred_table
                if parent not in predicates:
                    continue
                elements = tuple(constraint.elements)
                conditions.append(
                    tuple_(*(item.parent for item in elements)).in_(
                        select(*(item.column for item in elements)).where(predicates[parent])
                    )
                )
            if conditions:
                additions[table] = or_(*conditions)
        if not additions:
            return predicates
        predicates.update(additions)


def _require_idle(connection: Connection, predicates: dict[Table, ColumnElement[bool]]) -> None:
    for table, predicate in predicates.items():
        states = _BUSY.get(table.name)
        state = table.c.get("status") if "status" in table.c else table.c.get("state")
        if (
            states
            and state is not None
            and connection.execute(
                select(table).where(predicate, state.in_(states)).limit(1)
            ).first()
        ):
            raise _error(
                "project_deletion_busy",
                "Project still has running work. Stop or finish it before permanent deletion.",
            )
        if "lease_expires_at" in table.c:
            now = datetime.now(timezone.utc).isoformat()
            if connection.execute(
                select(table).where(predicate, table.c.lease_expires_at > now).limit(1)
            ).first():
                raise _error(
                    "project_deletion_busy",
                    "Project still has an active worker. Retry after it finishes.",
                )
        if (
            "lease_until" in table.c
            and connection.execute(
                select(table)
                .where(predicate, table.c.lease_until > int(datetime.now(timezone.utc).timestamp()))
                .limit(1)
            ).first()
        ):
            raise _error(
                "project_deletion_busy",
                "Project still has an active worker. Retry after it finishes.",
            )


def require_asset_not_purged(connection: Connection, asset_id: str) -> None:
    """Fence late reference admission against a committed deletion tombstone."""
    removed = func.json_each(_RECEIPTS.c.manifest_json, "$.asset_ids").table_valued(
        "value", joins_implicitly=True
    )
    if connection.execute(
        select(_RECEIPTS.c.project_id)
        .select_from(_RECEIPTS, removed)
        .where(removed.c.value == asset_id)
        .limit(1)
    ).first():
        raise _error("asset_not_found", "The referenced asset was permanently deleted.")


def require_workflow_not_purged(connection: Connection, workflow_id: str | None) -> None:
    if workflow_id is None:
        return
    removed = func.json_each(_RECEIPTS.c.manifest_json, "$.workflow_ids").table_valued(
        "value", joins_implicitly=True
    )
    if connection.execute(
        select(_RECEIPTS.c.project_id)
        .select_from(_RECEIPTS, removed)
        .where(removed.c.value == workflow_id)
        .limit(1)
    ).first():
        raise _error("workflow_not_found", "The source workflow was permanently deleted.")


def storage_key_is_referenced(connection: Connection, storage_key: str) -> bool:
    """Include durable publication intents that precede AssetVersion registration."""
    for table in Base.metadata.tables.values():
        if table is _RECEIPTS:
            continue
        for column in table.c:
            if column.name.endswith("storage_key"):
                query = select(column).where(column == storage_key)
            elif column.name.endswith("_json"):
                tree = func.json_tree(
                    case((func.json_valid(column), column), else_="{}")
                ).table_valued("value", joins_implicitly=True)
                query = (
                    select(tree.c.value).select_from(table, tree).where(tree.c.value == storage_key)
                )
            else:
                continue
            if connection.execute(query.limit(1)).first():
                return True
    return False


def _owned_assets(connection: Connection, workflow_ids: tuple[str, ...]) -> set[str]:
    versions = AssetVersionRow.__table__
    return set(
        connection.execute(
            select(versions.c.asset_id)
            .group_by(versions.c.asset_id)
            .having(
                func.sum(case((versions.c.source_workflow_id.in_(workflow_ids), 0), else_=1)) == 0
            )
        ).scalars()
    )


def referenced_asset_ids(connection: Connection, candidates: set[str]) -> set[str]:
    """Preserve explicit references, immutable JSON pins and reusable library members."""
    if not candidates:
        return set()
    versions = AssetVersionRow.__table__
    version_owners = dict(
        connection.execute(
            select(versions.c.version_id, versions.c.asset_id).where(
                versions.c.asset_id.in_(candidates)
            )
        ).all()
    )
    identities = set(version_owners) | candidates
    retained: set[str] = set()
    for batch in _batches(sorted(identities)):
        for table in Base.metadata.tables.values():
            if table.name in {"assets", "asset_versions", "project_deletion_receipts"}:
                continue
            for column in table.c:
                if column.name.endswith("_id"):
                    found = connection.execute(
                        select(column).where(column.in_(batch)).distinct()
                    ).scalars()
                elif column.name.endswith("_json"):
                    tree = func.json_tree(
                        case((func.json_valid(column), column), else_="{}")
                    ).table_valued("value", "type", joins_implicitly=True)
                    found = connection.execute(
                        select(tree.c.value)
                        .select_from(table, tree)
                        .where(tree.c.type == "text", tree.c.value.in_(batch))
                        .distinct()
                    ).scalars()
                else:
                    continue
                retained.update(version_owners.get(value, value) for value in found)
    # An externally retained derivative also pins its ancestors. Preserve whole
    # logical assets, including historical versions and cross-project lineage.
    while True:
        external = or_(~versions.c.asset_id.in_(candidates), versions.c.asset_id.in_(retained))
        parents = connection.execute(
            select(versions.c.parent_version_id).where(
                versions.c.parent_version_id.in_(version_owners),
                external,
            )
        ).scalars()
        inherited = {version_owners[value] for value in parents}
        for column in (versions.c.metadata_json, versions.c.quality_json):
            tree = func.json_tree(case((func.json_valid(column), column), else_="{}")).table_valued(
                "value", joins_implicitly=True
            )
            for batch in _batches(sorted(identities)):
                pins = connection.execute(
                    select(tree.c.value)
                    .select_from(versions, tree)
                    .where(external, tree.c.value.in_(batch))
                    .distinct()
                ).scalars()
                inherited.update(version_owners.get(value, value) for value in pins)
        if inherited <= retained:
            return retained
        retained.update(inherited)


def _delete_idempotency_payloads(
    connection: Connection, project_id: str, workflow_ids: tuple[str, ...]
) -> None:
    table = AgentCanvasIdempotencyRow.__table__
    payload = case((func.json_valid(table.c.response_json), table.c.response_json), else_="{}")
    connection.execute(
        delete(table).where(
            or_(
                func.json_extract(payload, "$.project_id") == project_id,
                func.json_extract(payload, "$.workflow_id").in_(workflow_ids),
                func.json_extract(payload, "$.workflow.workflow_id").in_(workflow_ids),
            )
        )
    )


def _delete_keys(connection: Connection, table: Table, keys: tuple[Any, ...]) -> None:
    for batch in _batches(list(keys)):
        connection.execute(delete(table).where(tuple_(*table.primary_key.columns).in_(batch)))


def _batches(items: list[Any]) -> Iterator[list[Any]]:
    for start in range(0, len(items), 200):
        yield items[start : start + 200]


def _require_version(current: int, expected: int) -> None:
    if current != expected:
        raise _error(
            "project_state_conflict", "Project version does not match the current version."
        )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="project_permanent_deletion")
