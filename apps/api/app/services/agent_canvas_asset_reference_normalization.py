"""Bounded normalization for legacy unversioned Canvas asset bindings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import insert, select, update

from app.persistence.database import V2Database
from app.persistence.models import AgentCanvasBindingRow, AssetVersionRow, DataMigrationRow
from app.services.agent_canvas_asset_reference_resolver import AgentCanvasAssetReferenceResolver


MIGRATION_NAME = "agent_canvas_direct_asset_binding_versions"


@dataclass(frozen=True, slots=True)
class AssetReferenceNormalizationReport:
    migration_name: str
    scanned: int
    backfilled: int
    already_normalized: int
    disabled: int
    audit: tuple[dict[str, str], ...]


class AgentCanvasAssetReferenceNormalizationService:
    """Normalize each legacy row once under a single SQLite write lock."""

    def __init__(self, database: V2Database, resolver: AgentCanvasAssetReferenceResolver) -> None:
        self._database = database
        self._resolver = resolver

    def normalize(self) -> AssetReferenceNormalizationReport:
        now = datetime.now(timezone.utc).isoformat()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            rows = (
                connection.execute(
                    select(AgentCanvasBindingRow).where(
                        AgentCanvasBindingRow.source_kind == "image_asset"
                    )
                )
                .mappings()
                .all()
            )
            audit: list[dict[str, str]] = []
            backfilled = 0
            already_normalized = 0
            disabled = 0
            for row in rows:
                binding_id = str(row["binding_id"])
                asset_id = str(row["source_asset_id"])
                version_id = row["source_asset_version_id"]
                if isinstance(version_id, str) and version_id:
                    already_normalized += 1
                    audit.append(
                        {
                            "binding_id": binding_id,
                            "asset_id": asset_id,
                            "status": "already_normalized",
                            "version_id": version_id,
                        }
                    )
                    continue
                candidates = (
                    connection.execute(
                        select(AssetVersionRow)
                        .where(
                            AssetVersionRow.asset_id == asset_id,
                            AssetVersionRow.status == "ready",
                        )
                        .order_by(
                            AssetVersionRow.version_no.desc(),
                            AssetVersionRow.version_id.desc(),
                        )
                    )
                    .mappings()
                    .all()
                )
                selected = None
                for candidate in candidates:
                    try:
                        self._resolver.resolve_bound_asset(
                            asset_id,
                            str(candidate["version_id"]),
                        )
                    except Exception:  # noqa: BLE001 - normalization must inspect all candidates.
                        continue
                    selected = candidate
                    break
                if selected is None:
                    metadata = json.loads(str(row["metadata_json"]))
                    metadata["canvas_reference_error"] = "canvas_asset_reference_version_required"
                    connection.execute(
                        update(AgentCanvasBindingRow)
                        .where(AgentCanvasBindingRow.binding_id == binding_id)
                        .values(enabled=False, metadata_json=_dump(metadata), updated_at=now)
                    )
                    disabled += 1
                    audit.append(
                        {
                            "binding_id": binding_id,
                            "asset_id": asset_id,
                            "status": "disabled",
                            "error_code": "canvas_asset_reference_version_required",
                        }
                    )
                    continue
                selected_version_id = str(selected["version_id"])
                connection.execute(
                    update(AgentCanvasBindingRow)
                    .where(AgentCanvasBindingRow.binding_id == binding_id)
                    .values(source_asset_version_id=selected_version_id, updated_at=now)
                )
                backfilled += 1
                audit.append(
                    {
                        "binding_id": binding_id,
                        "asset_id": asset_id,
                        "status": "backfilled",
                        "version_id": selected_version_id,
                    }
                )
            details = {
                "scanned": len(rows),
                "backfilled": backfilled,
                "already_normalized": already_normalized,
                "disabled": disabled,
                "audit": audit,
            }
            existing = connection.execute(
                select(DataMigrationRow.migration_name).where(
                    DataMigrationRow.migration_name == MIGRATION_NAME
                )
            ).scalar_one_or_none()
            values = {
                "status": "completed",
                "source_count": len(rows),
                "imported_count": backfilled,
                "started_at": now,
                "completed_at": now,
                "details_json": json.dumps(details, separators=(",", ":"), sort_keys=True),
            }
            if existing is None:
                connection.execute(
                    insert(DataMigrationRow).values(
                        migration_name=MIGRATION_NAME,
                        **values,
                    )
                )
            else:
                connection.execute(
                    update(DataMigrationRow)
                    .where(DataMigrationRow.migration_name == MIGRATION_NAME)
                    .values(**values)
                )
            connection.commit()
        return AssetReferenceNormalizationReport(
            migration_name=MIGRATION_NAME,
            scanned=len(rows),
            backfilled=backfilled,
            already_normalized=already_normalized,
            disabled=disabled,
            audit=tuple(audit),
        )


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
