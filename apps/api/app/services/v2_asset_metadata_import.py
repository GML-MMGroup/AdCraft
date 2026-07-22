"""One-time import of existing V2 asset metadata JSON into SQLite."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path

from pydantic import ValidationError

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.v2_asset_library import (
    AssetBindingCreate,
    AssetMetadataImportItemResultV2,
    AssetMetadataImportReportV2,
    AssetRecordCreate,
    AssetVersionCreate,
)
from app.schemas.v2_persistence import DataMigrationCompletion
from app.schemas.workflow_v2 import WorkflowAssetRelationV2, WorkflowAssetVersionV2
from app.services.v2_data_boundary import (
    V2DataBoundaryError,
    validate_v2_data_path,
    validate_v2_relative_path,
)


V2_ASSET_METADATA_IMPORT_MIGRATION_NAME = "v2_asset_metadata_import_v1"
_QUARANTINE_DIR = Path("v2") / "migration-quarantine" / "asset-metadata"


class V2AssetMetadataImportService:
    """Import canonical V2 metadata files without moving media or rewriting Workflows."""

    def __init__(
        self,
        data_dir: Path,
        repository: V2AssetLibraryRepository,
        events: EventRepository,
    ) -> None:
        self._data_dir = data_dir
        self._repository = repository
        self._events = events

    def import_if_required(self) -> AssetMetadataImportReportV2:
        """Idempotently import valid source records and quarantine malformed siblings."""

        if self._events.migration_status(V2_ASSET_METADATA_IMPORT_MIGRATION_NAME) == "completed":
            details = self._events.migration_details(V2_ASSET_METADATA_IMPORT_MIGRATION_NAME)
            if details is None:
                raise _import_error()
            try:
                return AssetMetadataImportReportV2.model_validate(details)
            except ValidationError as error:
                raise _import_error() from error

        items = [self._import_version(path) for path in self.discover_version_paths()]
        items.extend(self._import_relation(path) for path in self.discover_relation_paths())
        report = AssetMetadataImportReportV2(
            migration_name=V2_ASSET_METADATA_IMPORT_MIGRATION_NAME,
            items=tuple(items),
        )
        try:
            with self._repository.database.engine.begin() as connection:
                self._events.complete_migration_in_transaction(
                    connection,
                    DataMigrationCompletion(
                        migration_name=V2_ASSET_METADATA_IMPORT_MIGRATION_NAME,
                        source_count=len(items),
                        imported_count=(
                            report.imported_version_count + report.imported_binding_count
                        ),
                        completed_at=_utc_now(),
                        details=report.model_dump(mode="json"),
                    ),
                )
        except V2PersistenceError:
            raise
        except Exception as error:
            raise _import_error() from error
        return report

    def discover_version_paths(self) -> list[Path]:
        """Return only canonical asset-version metadata files in deterministic order."""

        metadata_root = self._data_dir / "assets" / "metadata"
        if not metadata_root.is_dir():
            return []
        return sorted(
            (path for path in metadata_root.glob("*/*.json") if path.parent.name != "relations"),
            key=lambda path: path.relative_to(self._data_dir).as_posix(),
        )

    def discover_relation_paths(self) -> list[Path]:
        """Return only current V2 relation metadata, never V1 library records."""

        root = self._data_dir / "assets" / "metadata" / "relations"
        if not root.is_dir():
            return []
        return sorted(root.glob("*.json"), key=lambda path: path.name)

    def _import_version(self, source_path: Path) -> AssetMetadataImportItemResultV2:
        relative_path = _relative_path(self._data_dir, source_path)
        try:
            record = WorkflowAssetVersionV2.model_validate_json(source_path.read_bytes())
            if record.asset_id != source_path.parent.name or record.version_id != source_path.stem:
                raise ValueError("asset metadata identity does not match its path")
            validate_v2_relative_path(record.file_path, operation="v2-asset-metadata-import")
            media_path = validate_v2_data_path(
                self._data_dir,
                record.file_path,
                operation="v2-asset-metadata-import",
            )
            if not media_path.is_file():
                raise ValueError("asset media is unavailable")
            self._repository.import_asset_version(
                _asset_from_legacy(record),
                _version_from_legacy(record, media_path),
            )
            return AssetMetadataImportItemResultV2(
                source_path=relative_path,
                record_kind="version",
                status="imported",
                asset_id=record.asset_id,
                version_id=record.version_id,
            )
        except (
            OSError,
            ValueError,
            ValidationError,
            V2DataBoundaryError,
            V2PersistenceError,
        ) as error:
            if (
                isinstance(error, V2PersistenceError)
                and error.code == "v2_asset_library_persistence_failed"
            ):
                raise
            return self._quarantine(relative_path, "version", error)

    def _import_relation(self, source_path: Path) -> AssetMetadataImportItemResultV2:
        relative_path = _relative_path(self._data_dir, source_path)
        try:
            relation = WorkflowAssetRelationV2.model_validate_json(source_path.read_bytes())
            if relation.relation_id != source_path.stem:
                raise ValueError("relation metadata identity does not match its path")
            version_id = relation.metadata.get("version_id")
            if not isinstance(version_id, str) or not version_id:
                raise ValueError("relation has no immutable version pin")
            if relation.target_workflow_id is None:
                raise ValueError("relation has no workflow target")
            self._repository.import_binding(
                AssetBindingCreate(
                    binding_id=relation.relation_id,
                    selection_group_id=f"legacy:{relation.relation_id}",
                    binding_type=relation.relation_type,
                    workflow_id=relation.target_workflow_id,
                    target_node_id=relation.target_node_id,
                    target_item_id=relation.target_item_id,
                    target_slot_id=relation.target_slot_id,
                    asset_id=relation.source_asset_id,
                    version_id=version_id,
                    reference_role=_optional_metadata_string(relation.metadata, "reference_role"),
                    use_as_prompt=True,
                    sort_order=0,
                    metadata={
                        "workflow_asset_relation": relation.model_dump(mode="json"),
                        "legacy_relation_type": relation.relation_type,
                        "legacy_metadata": relation.metadata,
                    },
                    created_at=relation.created_at,
                )
            )
            return AssetMetadataImportItemResultV2(
                source_path=relative_path,
                record_kind="relation",
                status="imported",
                asset_id=relation.source_asset_id,
                version_id=version_id,
                binding_id=relation.relation_id,
            )
        except (OSError, ValueError, ValidationError, V2PersistenceError) as error:
            if (
                isinstance(error, V2PersistenceError)
                and error.code == "v2_asset_library_persistence_failed"
            ):
                raise
            return self._quarantine(relative_path, "relation", error)

    def _quarantine(
        self,
        source_path: str,
        record_kind: str,
        error: BaseException,
    ) -> AssetMetadataImportItemResultV2:
        validation_paths = _validation_paths(error)
        diagnostic = {
            "source_path": source_path,
            "record_kind": record_kind,
            "error_code": "asset_metadata_import_quarantined",
            "validation_paths": list(validation_paths),
            "recorded_at": _utc_now(),
        }
        quarantine_root = self._data_dir / _QUARANTINE_DIR
        quarantine_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]
        destination = quarantine_root / f"{record_kind}-{digest}.json"
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            temporary.write_text(
                json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except OSError as write_error:
            raise _import_error() from write_error
        finally:
            temporary.unlink(missing_ok=True)
        return AssetMetadataImportItemResultV2(
            source_path=source_path,
            record_kind="version" if record_kind == "version" else "relation",
            status="quarantined",
            error_code="asset_metadata_import_quarantined",
            validation_paths=validation_paths,
        )


def _asset_from_legacy(record: WorkflowAssetVersionV2) -> AssetRecordCreate:
    display_name = _optional_metadata_string(record.metadata, "display_name") or record.asset_id
    return AssetRecordCreate(
        asset_id=record.asset_id,
        media_type=record.media_type,
        source_type=_source_type_from_legacy(record.source_type),
        display_name=display_name,
        created_at=record.created_at,
        updated_at=record.created_at,
    )


def _version_from_legacy(record: WorkflowAssetVersionV2, media_path: Path) -> AssetVersionCreate:
    metadata = {
        "workflow_asset_version": record.model_dump(mode="json"),
        "legacy_public_url": record.public_url,
        "legacy_thumbnail_path": record.thumbnail_path,
        "legacy_proxy_path": record.proxy_path,
        "legacy_rendition_paths": record.rendition_paths,
        "legacy_workflow_id": record.workflow_id,
        "legacy_node_id": record.node_id,
        "legacy_item_id": record.item_id,
        "legacy_slot_id": record.slot_id,
        "legacy_semantic_type": record.semantic_type,
        "legacy_prompt_snapshot": record.prompt_snapshot,
        "legacy_provider_payload_snapshot": record.provider_payload_snapshot,
        "legacy_reference_asset_ids": record.reference_asset_ids,
        "legacy_library_entity_id": record.library_entity_id,
        "legacy_created_by": record.created_by,
        "legacy_metadata": record.metadata,
    }
    mime_type = _optional_metadata_string(record.metadata, "content_type") or (
        mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    )
    return AssetVersionCreate(
        version_id=record.version_id,
        asset_id=record.asset_id,
        storage_key=record.file_path,
        sha256=_sha256(media_path),
        size_bytes=media_path.stat().st_size,
        mime_type=mime_type,
        source_workflow_id=record.workflow_id,
        source_node_id=record.node_id,
        source_item_id=record.item_id,
        source_slot_id=record.slot_id,
        metadata=metadata,
        created_at=record.created_at,
    )


def _source_type_from_legacy(value: str) -> str:
    if value in {"upload", "generated", "derived"}:
        return value
    return "derived"


def _optional_metadata_string(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _relative_path(data_dir: Path, path: Path) -> str:
    return path.relative_to(data_dir).as_posix()


def _validation_paths(error: BaseException) -> tuple[str, ...]:
    if isinstance(error, ValidationError):
        return tuple(
            ".".join(str(part) for part in item["loc"])[:256] for item in error.errors()[:20]
        )
    return ()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    from app.services.agent_trace import utc_now

    return utc_now().isoformat()


def _import_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_asset_metadata_import_failed",
        "V2 asset metadata import failed.",
        stage="asset_metadata_import",
    )
