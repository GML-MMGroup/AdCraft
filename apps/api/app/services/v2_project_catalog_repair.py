"""One-time repair for unusable Agent Canvas Project catalog rows."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasWorkflowRow, ProjectRow, WorkflowRow
from app.schemas.v2_persistence import (
    DataMigrationCompletion,
    ProjectCatalogRepairReportV2,
)

V2_PROJECT_CATALOG_ORPHAN_CLEANUP_MIGRATION_NAME = "v2_project_catalog_orphan_cleanup_v1"


class V2ProjectCatalogRepairService:
    """Remove pre-release Projects that have no Agent Canvas Workflow."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Project catalog repair repositories must share one V2Database.")
        self._database = database
        self._events = events

    def repair_if_required(self) -> ProjectCatalogRepairReportV2:
        """Run the cleanup once and return its durable audit report."""

        try:
            if (
                self._events.migration_status(V2_PROJECT_CATALOG_ORPHAN_CLEANUP_MIGRATION_NAME)
                == "completed"
            ):
                details = self._events.migration_details(
                    V2_PROJECT_CATALOG_ORPHAN_CLEANUP_MIGRATION_NAME
                )
                if details is None:
                    raise _repair_error()
                return ProjectCatalogRepairReportV2.model_validate(details)

            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    scanned_count = int(
                        connection.execute(
                            select(func.count()).select_from(ProjectRow)
                        ).scalar_one()
                    )
                    removed_project_ids = tuple(
                        str(project_id)
                        for project_id in connection.execute(
                            select(ProjectRow.project_id)
                            .outerjoin(
                                AgentCanvasWorkflowRow,
                                AgentCanvasWorkflowRow.project_id == ProjectRow.project_id,
                            )
                            .outerjoin(
                                WorkflowRow,
                                WorkflowRow.project_id == ProjectRow.project_id,
                            )
                            .where(
                                AgentCanvasWorkflowRow.project_id.is_(None),
                                WorkflowRow.project_id.is_(None),
                            )
                            .order_by(ProjectRow.project_id.asc())
                        ).scalars()
                    )
                    if removed_project_ids:
                        connection.execute(
                            delete(ProjectRow).where(ProjectRow.project_id.in_(removed_project_ids))
                        )
                    report = ProjectCatalogRepairReportV2(
                        migration_name=V2_PROJECT_CATALOG_ORPHAN_CLEANUP_MIGRATION_NAME,
                        scanned_count=scanned_count,
                        removed_count=len(removed_project_ids),
                        removed_project_ids=removed_project_ids,
                    )
                    self._events.complete_migration_in_transaction(
                        connection,
                        DataMigrationCompletion(
                            migration_name=report.migration_name,
                            source_count=report.scanned_count,
                            imported_count=report.removed_count,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                            details=report.model_dump(mode="json"),
                        ),
                    )
                    connection.commit()
                    return report
                except BaseException:
                    connection.rollback()
                    raise
        except Exception as error:
            if isinstance(error, V2PersistenceError) and error.code == (
                "project_catalog_repair_failed"
            ):
                raise
            raise _repair_error() from error


def _repair_error() -> V2PersistenceError:
    return V2PersistenceError(
        "project_catalog_repair_failed",
        "Project catalog repair failed.",
        stage="project_catalog_repair",
    )
