"""Focused SQLite persistence for V2 unified asset-library metadata."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import cast

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import (
    AssetBindingRow,
    AssetCatalogRow,
    AssetEntityMemberRow,
    AssetEntityRow,
    AssetRow,
    AssetVersionRow,
)
from app.schemas.v2_asset_library import (
    AssetBindingCreate,
    AssetBindingV2,
    AssetCatalogRecordV2,
    AssetEntityCreate,
    AssetEntityMemberCreate,
    AssetEntityMemberV2,
    AssetEntityScopeV2,
    AssetEntityStatusV2,
    AssetLibraryCategoryV2,
    AssetLibraryEntityDetailV2,
    AssetLibraryEntityPageV2,
    AssetLibraryEntitySummaryV2,
    AssetRecordCreate,
    AssetVersionCreate,
    AssetVersionMetadataV2,
    UpdateAssetLibraryEntityRequestV2,
)


class V2AssetLibraryRepository:
    """Own relational asset metadata; media and provider work stay outside this class."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    @property
    def database(self) -> V2Database:
        """Return the database identity used by caller-owned transactions."""

        return self._database

    def upsert_catalog(
        self,
        catalog: AssetCatalogRecordV2,
        *,
        connection: Connection | None = None,
    ) -> AssetCatalogRecordV2:
        """Persist catalog metadata without performing installation work."""

        if connection is not None:
            return self._upsert_catalog_in_transaction(connection, catalog)
        try:
            with self._database.engine.begin() as connection:
                self._upsert_catalog_in_transaction(connection, catalog)
        except IntegrityError as error:
            raise _catalog_conflict_error() from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return self.get_catalog(catalog.catalog_id)

    def _upsert_catalog_in_transaction(
        self,
        connection: Connection,
        catalog: AssetCatalogRecordV2,
    ) -> AssetCatalogRecordV2:
        """Upsert catalog metadata inside a caller-owned short transaction."""

        values = _catalog_values(catalog)
        existing = connection.execute(
            select(AssetCatalogRow.catalog_id).where(
                AssetCatalogRow.catalog_id == catalog.catalog_id
            )
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(insert(AssetCatalogRow).values(**values))
        else:
            connection.execute(
                update(AssetCatalogRow)
                .where(AssetCatalogRow.catalog_id == catalog.catalog_id)
                .values(**values)
            )
        row = (
            connection.execute(
                select(AssetCatalogRow).where(AssetCatalogRow.catalog_id == catalog.catalog_id)
            )
            .mappings()
            .one()
        )
        return _catalog_from_row(row)

    def get_catalog(self, catalog_id: str) -> AssetCatalogRecordV2:
        """Return one persisted catalog or raise the stable not-found error."""

        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AssetCatalogRow).where(AssetCatalogRow.catalog_id == catalog_id)
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise _catalog_not_found_error()
        return _catalog_from_row(row)

    def create_asset_version(
        self,
        asset: AssetRecordCreate,
        version: AssetVersionCreate,
        *,
        connection: Connection | None = None,
    ) -> AssetVersionMetadataV2:
        """Create an immutable logical asset/version pair in one short transaction."""

        if asset.asset_id != version.asset_id:
            raise V2PersistenceError(
                "asset_version_asset_mismatch",
                "Asset version does not belong to the supplied asset.",
                stage="asset_library_repository",
            )
        if connection is not None:
            return self._create_asset_version_in_transaction(connection, asset, version)
        try:
            with self._database.engine.begin() as transaction:
                created = self._create_asset_version_in_transaction(transaction, asset, version)
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _asset_version_conflict_error() from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return created

    def import_asset_version(
        self,
        asset: AssetRecordCreate,
        version: AssetVersionCreate,
        *,
        connection: Connection | None = None,
    ) -> AssetVersionMetadataV2:
        """Idempotently import a stable legacy version without mutating an existing row."""

        if connection is not None:
            return self._import_asset_version_in_transaction(connection, asset, version)
        try:
            with self._database.engine.begin() as transaction:
                imported = self._import_asset_version_in_transaction(transaction, asset, version)
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _asset_version_conflict_error() from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return imported

    def create_entity(
        self,
        entity: AssetEntityCreate,
        *,
        members: tuple[AssetEntityMemberCreate, ...] = (),
        connection: Connection | None = None,
    ) -> AssetLibraryEntityDetailV2:
        """Create an entity and all immutable member pins atomically."""

        if connection is not None:
            return self._create_entity_in_transaction(connection, entity, members)
        try:
            with self._database.engine.begin() as transaction:
                created = self._create_entity_in_transaction(transaction, entity, members)
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _entity_conflict_error() from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return created

    def get_entity(
        self, entity_id: str, *, connection: Connection | None = None
    ) -> AssetLibraryEntityDetailV2:
        """Load an entity and its ordered version-pinned members."""

        if connection is not None:
            return _get_entity_detail(connection, entity_id)
        try:
            with self._database.engine.connect() as transaction:
                return _get_entity_detail(transaction, entity_id)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def list_entities(
        self,
        *,
        scope: AssetEntityScopeV2 | None = None,
        category: AssetLibraryCategoryV2 | None = None,
        status: AssetEntityStatusV2 = "active",
        search: str | None = None,
        limit: int = 40,
        cursor: str | None = None,
        connection: Connection | None = None,
    ) -> AssetLibraryEntityPageV2:
        """List entity metadata in a bounded deterministic order."""

        if not 1 <= limit <= 100:
            raise V2PersistenceError(
                "asset_library_page_invalid",
                "Asset library page bounds are invalid.",
                stage="asset_library_repository",
            )
        cursor_values = _decode_cursor(cursor) if cursor is not None else None
        if connection is not None:
            return _list_entities(
                connection,
                scope=scope,
                category=category,
                status=status,
                search=search,
                limit=limit,
                cursor_values=cursor_values,
            )
        try:
            with self._database.engine.connect() as transaction:
                return _list_entities(
                    transaction,
                    scope=scope,
                    category=category,
                    status=status,
                    search=search,
                    limit=limit,
                    cursor_values=cursor_values,
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def update_user_entity(
        self,
        entity_id: str,
        changes: UpdateAssetLibraryEntityRequestV2,
    ) -> AssetLibraryEntityDetailV2:
        """Update permitted metadata for a user entity only."""

        values = changes.model_dump(exclude_none=True)
        if not values:
            return self.get_entity(entity_id)
        if "tags" in values:
            values["tags_json"] = _json(values.pop("tags"))
        values["updated_at"] = _utc_now()
        try:
            with self._database.engine.begin() as connection:
                current = _get_entity_row(connection, entity_id)
                _require_user_entity(current)
                connection.execute(
                    update(AssetEntityRow)
                    .where(AssetEntityRow.entity_id == entity_id)
                    .values(**values)
                )
                return _get_entity_detail(connection, entity_id)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def trash_user_entity(self, entity_id: str) -> AssetLibraryEntityDetailV2:
        """Soft-trash a user entity without deleting assets, versions, or bindings."""

        return self._change_entity_lifecycle(entity_id, status="trashed")

    def restore_user_entity(self, entity_id: str) -> AssetLibraryEntityDetailV2:
        """Restore a trashed user entity without changing its immutable members."""

        return self._change_entity_lifecycle(entity_id, status="active")

    def resolve_versions(
        self,
        version_ids: tuple[str, ...],
        *,
        connection: Connection | None = None,
    ) -> tuple[AssetVersionMetadataV2, ...]:
        """Resolve stable version IDs in caller order without filesystem access."""

        if not version_ids:
            return ()
        if connection is not None:
            return _resolve_versions(connection, version_ids)
        try:
            with self._database.engine.connect() as transaction:
                return _resolve_versions(transaction, version_ids)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def find_version(
        self,
        *,
        asset_id: str | None = None,
        version_id: str | None = None,
        slot_id: str | None = None,
        connection: Connection | None = None,
    ) -> AssetVersionMetadataV2 | None:
        """Find one immutable version using existing V2 compatibility identifiers."""

        if connection is not None:
            return _find_version(
                connection,
                asset_id=asset_id,
                version_id=version_id,
                slot_id=slot_id,
            )
        try:
            with self._database.engine.connect() as transaction:
                return _find_version(
                    transaction,
                    asset_id=asset_id,
                    version_id=version_id,
                    slot_id=slot_id,
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def create_binding(
        self,
        binding: AssetBindingCreate,
        *,
        connection: Connection | None = None,
    ) -> AssetBindingV2:
        """Persist a version-pinned reference binding without authoring mutations."""

        if connection is not None:
            return self._create_binding_in_transaction(connection, binding)
        try:
            with self._database.engine.begin() as transaction:
                created = self._create_binding_in_transaction(transaction, binding)
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _binding_conflict_error() from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return created

    def import_binding(
        self,
        binding: AssetBindingCreate,
        *,
        connection: Connection | None = None,
    ) -> AssetBindingV2:
        """Idempotently import a stable legacy relation as a pinned binding."""

        if connection is not None:
            return self._import_binding_in_transaction(connection, binding)
        try:
            with self._database.engine.begin() as transaction:
                imported = self._import_binding_in_transaction(transaction, binding)
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _binding_conflict_error() from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return imported

    def remove_binding(
        self,
        binding_id: str,
        *,
        connection: Connection | None = None,
    ) -> AssetBindingV2:
        """Soft-remove a binding while retaining its asset and version history."""

        if connection is not None:
            return self._remove_binding_in_transaction(connection, binding_id)
        try:
            with self._database.engine.begin() as transaction:
                removed = self._remove_binding_in_transaction(transaction, binding_id)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return removed

    def restore_binding(self, binding_id: str) -> AssetBindingV2:
        """Reactivate one binding only for a failed authoring compensation path."""

        try:
            with self._database.engine.begin() as connection:
                row = _get_binding(connection, binding_id)
                if row is None:
                    raise V2PersistenceError(
                        "asset_binding_not_found",
                        "Asset binding was not found.",
                        stage="asset_library_repository",
                    )
                connection.execute(
                    update(AssetBindingRow)
                    .where(AssetBindingRow.binding_id == binding_id)
                    .values(status="active", removed_at=None)
                )
                restored = _get_binding(connection, binding_id)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if restored is None:
            raise _persistence_error()
        return restored

    def get_binding(
        self, binding_id: str, *, connection: Connection | None = None
    ) -> AssetBindingV2 | None:
        """Return one binding without changing its lifecycle state."""

        if connection is not None:
            return _get_binding(connection, binding_id)
        try:
            with self._database.engine.connect() as transaction:
                return _get_binding(transaction, binding_id)
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def list_bindings(
        self,
        *,
        workflow_id: str | None = None,
        target_slot_id: str | None = None,
        asset_id: str | None = None,
        binding_type: str | None = None,
        include_removed: bool = False,
        connection: Connection | None = None,
    ) -> tuple[AssetBindingV2, ...]:
        """List deterministic bindings for the V2 compatibility projection."""

        if connection is not None:
            return _list_bindings(
                connection,
                workflow_id=workflow_id,
                target_slot_id=target_slot_id,
                asset_id=asset_id,
                binding_type=binding_type,
                include_removed=include_removed,
            )
        try:
            with self._database.engine.connect() as transaction:
                return _list_bindings(
                    transaction,
                    workflow_id=workflow_id,
                    target_slot_id=target_slot_id,
                    asset_id=asset_id,
                    binding_type=binding_type,
                    include_removed=include_removed,
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def _create_asset_version_in_transaction(
        self,
        connection: Connection,
        asset: AssetRecordCreate,
        version: AssetVersionCreate,
    ) -> AssetVersionMetadataV2:
        existing_asset = connection.execute(
            select(AssetRow.asset_id).where(AssetRow.asset_id == asset.asset_id)
        ).scalar_one_or_none()
        now = _utc_now()
        if existing_asset is None:
            connection.execute(
                insert(AssetRow).values(
                    asset_id=asset.asset_id,
                    media_type=asset.media_type,
                    source_type=asset.source_type,
                    display_name=asset.display_name,
                    status=asset.status,
                    created_at=asset.created_at or now,
                    updated_at=asset.updated_at or asset.created_at or now,
                )
            )
        existing_version = connection.execute(
            select(AssetVersionRow.version_id).where(
                AssetVersionRow.version_id == version.version_id
            )
        ).scalar_one_or_none()
        if existing_version is not None:
            raise _asset_version_conflict_error()
        version_no = version.version_no
        if version_no is None:
            version_no = (
                int(
                    connection.execute(
                        select(func.coalesce(func.max(AssetVersionRow.version_no), 0)).where(
                            AssetVersionRow.asset_id == asset.asset_id
                        )
                    ).scalar_one()
                )
                + 1
            )
        connection.execute(
            insert(AssetVersionRow).values(
                version_id=version.version_id,
                asset_id=asset.asset_id,
                version_no=version_no,
                storage_key=version.storage_key,
                sha256=version.sha256,
                size_bytes=version.size_bytes,
                mime_type=version.mime_type,
                width=version.width,
                height=version.height,
                duration_seconds=version.duration_seconds,
                prompt=version.prompt,
                provider=version.provider,
                model_id=version.model_id,
                source_workflow_id=version.source_workflow_id,
                source_node_id=version.source_node_id,
                source_item_id=version.source_item_id,
                source_slot_id=version.source_slot_id,
                parent_version_id=version.parent_version_id,
                quality_json=_json(version.quality) if version.quality is not None else None,
                metadata_json=_json(version.metadata),
                status=version.status,
                created_at=version.created_at or now,
            )
        )
        return _get_version(connection, version.version_id)

    def _import_asset_version_in_transaction(
        self,
        connection: Connection,
        asset: AssetRecordCreate,
        version: AssetVersionCreate,
    ) -> AssetVersionMetadataV2:
        existing = connection.execute(
            select(AssetVersionRow.version_id).where(
                AssetVersionRow.version_id == version.version_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _get_version(connection, version.version_id)
        return self._create_asset_version_in_transaction(connection, asset, version)

    def _create_entity_in_transaction(
        self,
        connection: Connection,
        entity: AssetEntityCreate,
        members: tuple[AssetEntityMemberCreate, ...],
    ) -> AssetLibraryEntityDetailV2:
        existing = connection.execute(
            select(AssetEntityRow.entity_id).where(AssetEntityRow.entity_id == entity.entity_id)
        ).scalar_one_or_none()
        if existing is not None:
            raise _entity_conflict_error()
        now = _utc_now()
        connection.execute(
            insert(AssetEntityRow).values(
                entity_id=entity.entity_id,
                scope=entity.scope,
                entity_type=entity.entity_type,
                library_category=entity.library_category,
                display_name=entity.display_name,
                description=entity.description,
                tags_json=_json(entity.tags),
                is_favorite=entity.is_favorite,
                catalog_id=entity.catalog_id,
                derived_from_entity_id=entity.derived_from_entity_id,
                status=entity.status,
                deleted_at=entity.deleted_at,
                created_at=entity.created_at or now,
                updated_at=entity.updated_at or entity.created_at or now,
            )
        )
        for member in members:
            version = _get_version(connection, member.version_id)
            if version.asset_id != member.asset_id:
                raise V2PersistenceError(
                    "asset_member_version_mismatch",
                    "Asset member does not match its pinned version.",
                    stage="asset_library_repository",
                )
            connection.execute(
                insert(AssetEntityMemberRow).values(
                    member_id=member.member_id,
                    entity_id=entity.entity_id,
                    asset_id=member.asset_id,
                    version_id=member.version_id,
                    semantic_type=member.semantic_type,
                    is_primary=member.is_primary,
                    is_default_reference=member.is_default_reference,
                    sort_order=member.sort_order,
                    created_at=member.created_at or now,
                )
            )
        return _get_entity_detail(connection, entity.entity_id)

    def _change_entity_lifecycle(
        self,
        entity_id: str,
        *,
        status: AssetEntityStatusV2,
    ) -> AssetLibraryEntityDetailV2:
        try:
            with self._database.engine.begin() as connection:
                _require_user_entity(_get_entity_row(connection, entity_id))
                now = _utc_now()
                connection.execute(
                    update(AssetEntityRow)
                    .where(AssetEntityRow.entity_id == entity_id)
                    .values(
                        status=status,
                        deleted_at=now if status == "trashed" else None,
                        updated_at=now,
                    )
                )
                return _get_entity_detail(connection, entity_id)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def _create_binding_in_transaction(
        self, connection: Connection, binding: AssetBindingCreate
    ) -> AssetBindingV2:
        version = _get_version(connection, binding.version_id)
        if version.asset_id != binding.asset_id:
            raise V2PersistenceError(
                "asset_binding_version_mismatch",
                "Asset binding does not match its pinned version.",
                stage="asset_library_repository",
            )
        if binding.source_entity_id is not None:
            _get_entity_row(connection, binding.source_entity_id)
        created_at = binding.created_at or _utc_now()
        connection.execute(
            insert(AssetBindingRow).values(
                binding_id=binding.binding_id,
                selection_group_id=binding.selection_group_id,
                binding_type=binding.binding_type,
                workflow_id=binding.workflow_id,
                target_node_id=binding.target_node_id,
                target_item_id=binding.target_item_id,
                target_slot_id=binding.target_slot_id,
                source_entity_id=binding.source_entity_id,
                asset_id=binding.asset_id,
                version_id=binding.version_id,
                reference_role=binding.reference_role,
                use_as_prompt=binding.use_as_prompt,
                sort_order=binding.sort_order,
                status=binding.status,
                removed_at=binding.removed_at,
                metadata_json=_json(binding.metadata),
                created_at=created_at,
            )
        )
        return binding.model_copy(update={"created_at": created_at})

    def _remove_binding_in_transaction(
        self, connection: Connection, binding_id: str
    ) -> AssetBindingV2:
        row = (
            connection.execute(
                select(AssetBindingRow).where(AssetBindingRow.binding_id == binding_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise V2PersistenceError(
                "asset_binding_not_found",
                "Asset binding was not found.",
                stage="asset_library_repository",
            )
        if row["status"] != "removed":
            removed_at = _utc_now()
            connection.execute(
                update(AssetBindingRow)
                .where(AssetBindingRow.binding_id == binding_id)
                .values(status="removed", removed_at=removed_at)
            )
            row = (
                connection.execute(
                    select(AssetBindingRow).where(AssetBindingRow.binding_id == binding_id)
                )
                .mappings()
                .one()
            )
        return _binding_from_row(row)

    def _import_binding_in_transaction(
        self, connection: Connection, binding: AssetBindingCreate
    ) -> AssetBindingV2:
        existing = (
            connection.execute(
                select(AssetBindingRow).where(AssetBindingRow.binding_id == binding.binding_id)
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            return _binding_from_row(existing)
        return self._create_binding_in_transaction(connection, binding)


def _list_entities(
    connection: Connection,
    *,
    scope: AssetEntityScopeV2 | None,
    category: AssetLibraryCategoryV2 | None,
    status: AssetEntityStatusV2,
    search: str | None,
    limit: int,
    cursor_values: tuple[str, str] | None,
) -> AssetLibraryEntityPageV2:
    query = _entity_select().where(AssetEntityRow.status == status)
    if scope is not None:
        query = query.where(AssetEntityRow.scope == scope)
    if category is not None:
        query = query.where(AssetEntityRow.library_category == category)
    if search is not None and search.strip():
        query = query.where(AssetEntityRow.display_name.ilike(f"%{search.strip()}%"))
    if cursor_values is not None:
        cursor_updated_at, cursor_entity_id = cursor_values
        query = query.where(
            or_(
                AssetEntityRow.updated_at < cursor_updated_at,
                and_(
                    AssetEntityRow.updated_at == cursor_updated_at,
                    AssetEntityRow.entity_id > cursor_entity_id,
                ),
            )
        )
    rows = (
        connection.execute(
            query.order_by(AssetEntityRow.updated_at.desc(), AssetEntityRow.entity_id.asc()).limit(
                limit + 1
            )
        )
        .mappings()
        .all()
    )
    items = tuple(_entity_summary_from_row(row) for row in rows[:limit])
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = _encode_cursor(last.updated_at, last.entity_id)
    return AssetLibraryEntityPageV2(items=items, next_cursor=next_cursor)


def _get_entity_row(connection: Connection, entity_id: str) -> RowMapping:
    row = (
        connection.execute(_entity_select().where(AssetEntityRow.entity_id == entity_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _entity_not_found_error()
    return row


def _get_entity_detail(connection: Connection, entity_id: str) -> AssetLibraryEntityDetailV2:
    entity = _entity_summary_from_row(_get_entity_row(connection, entity_id))
    member_rows = (
        connection.execute(
            select(
                AssetEntityMemberRow.member_id,
                AssetEntityMemberRow.entity_id,
                AssetEntityMemberRow.asset_id,
                AssetEntityMemberRow.version_id,
                AssetEntityMemberRow.semantic_type,
                AssetEntityMemberRow.is_primary,
                AssetEntityMemberRow.is_default_reference,
                AssetEntityMemberRow.sort_order,
                AssetEntityMemberRow.created_at,
            )
            .where(AssetEntityMemberRow.entity_id == entity_id)
            .order_by(AssetEntityMemberRow.sort_order.asc(), AssetEntityMemberRow.member_id.asc())
        )
        .mappings()
        .all()
    )
    members = tuple(
        AssetEntityMemberV2(
            member_id=str(row["member_id"]),
            entity_id=str(row["entity_id"]),
            asset_id=str(row["asset_id"]),
            version_id=str(row["version_id"]),
            semantic_type=str(row["semantic_type"]),
            is_primary=bool(row["is_primary"]),
            is_default_reference=bool(row["is_default_reference"]),
            sort_order=int(row["sort_order"]),
            created_at=str(row["created_at"]),
            version=_get_version(connection, str(row["version_id"])),
        )
        for row in member_rows
    )
    return AssetLibraryEntityDetailV2(**entity.model_dump(), members=members)


def _resolve_versions(
    connection: Connection, version_ids: tuple[str, ...]
) -> tuple[AssetVersionMetadataV2, ...]:
    unique_ids = tuple(dict.fromkeys(version_ids))
    rows = (
        connection.execute(_version_select().where(AssetVersionRow.version_id.in_(unique_ids)))
        .mappings()
        .all()
    )
    versions = {str(row["version_id"]): _version_from_row(row) for row in rows}
    missing = [version_id for version_id in unique_ids if version_id not in versions]
    if missing:
        raise V2PersistenceError(
            "asset_version_not_found",
            "Asset version was not found.",
            stage="asset_library_repository",
        )
    return tuple(versions[version_id] for version_id in version_ids)


def _get_version(connection: Connection, version_id: str) -> AssetVersionMetadataV2:
    row = (
        connection.execute(_version_select().where(AssetVersionRow.version_id == version_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise V2PersistenceError(
            "asset_version_not_found",
            "Asset version was not found.",
            stage="asset_library_repository",
        )
    return _version_from_row(row)


def _find_version(
    connection: Connection,
    *,
    asset_id: str | None,
    version_id: str | None,
    slot_id: str | None,
) -> AssetVersionMetadataV2 | None:
    query = _version_select()
    if asset_id is not None:
        query = query.where(AssetVersionRow.asset_id == asset_id)
    if version_id is not None:
        query = query.where(AssetVersionRow.version_id == version_id)
    if slot_id is not None:
        query = query.where(AssetVersionRow.source_slot_id == slot_id)
    row = (
        connection.execute(
            query.order_by(AssetVersionRow.version_no.desc(), AssetVersionRow.version_id.desc())
        )
        .mappings()
        .first()
    )
    return None if row is None else _version_from_row(row)


def _get_binding(connection: Connection, binding_id: str) -> AssetBindingV2 | None:
    row = (
        connection.execute(_binding_select().where(AssetBindingRow.binding_id == binding_id))
        .mappings()
        .one_or_none()
    )
    return None if row is None else _binding_from_row(row)


def _list_bindings(
    connection: Connection,
    *,
    workflow_id: str | None,
    target_slot_id: str | None,
    asset_id: str | None,
    binding_type: str | None,
    include_removed: bool,
) -> tuple[AssetBindingV2, ...]:
    query = _binding_select()
    if workflow_id is not None:
        query = query.where(AssetBindingRow.workflow_id == workflow_id)
    if target_slot_id is not None:
        query = query.where(AssetBindingRow.target_slot_id == target_slot_id)
    if asset_id is not None:
        query = query.where(AssetBindingRow.asset_id == asset_id)
    if binding_type is not None:
        query = query.where(AssetBindingRow.binding_type == binding_type)
    if not include_removed:
        query = query.where(AssetBindingRow.status == "active")
    rows = (
        connection.execute(
            query.order_by(
                AssetBindingRow.sort_order.asc(),
                AssetBindingRow.created_at.asc(),
                AssetBindingRow.binding_id.asc(),
            )
        )
        .mappings()
        .all()
    )
    return tuple(_binding_from_row(row) for row in rows)


def _entity_select():
    return select(
        AssetEntityRow.entity_id,
        AssetEntityRow.scope,
        AssetEntityRow.entity_type,
        AssetEntityRow.library_category,
        AssetEntityRow.display_name,
        AssetEntityRow.description,
        AssetEntityRow.tags_json,
        AssetEntityRow.is_favorite,
        AssetEntityRow.catalog_id,
        AssetEntityRow.derived_from_entity_id,
        AssetEntityRow.status,
        AssetEntityRow.created_at,
        AssetEntityRow.updated_at,
        AssetEntityRow.deleted_at,
    )


def _version_select():
    return select(
        AssetVersionRow.version_id,
        AssetVersionRow.asset_id,
        AssetVersionRow.version_no,
        AssetVersionRow.storage_key,
        AssetVersionRow.sha256,
        AssetVersionRow.size_bytes,
        AssetVersionRow.mime_type,
        AssetVersionRow.width,
        AssetVersionRow.height,
        AssetVersionRow.duration_seconds,
        AssetVersionRow.prompt,
        AssetVersionRow.provider,
        AssetVersionRow.model_id,
        AssetVersionRow.source_workflow_id,
        AssetVersionRow.source_node_id,
        AssetVersionRow.source_item_id,
        AssetVersionRow.source_slot_id,
        AssetVersionRow.parent_version_id,
        AssetVersionRow.quality_json,
        AssetVersionRow.metadata_json,
        AssetVersionRow.status,
        AssetVersionRow.created_at,
    )


def _binding_select():
    return select(
        AssetBindingRow.binding_id,
        AssetBindingRow.selection_group_id,
        AssetBindingRow.binding_type,
        AssetBindingRow.workflow_id,
        AssetBindingRow.target_node_id,
        AssetBindingRow.target_item_id,
        AssetBindingRow.target_slot_id,
        AssetBindingRow.source_entity_id,
        AssetBindingRow.asset_id,
        AssetBindingRow.version_id,
        AssetBindingRow.reference_role,
        AssetBindingRow.use_as_prompt,
        AssetBindingRow.sort_order,
        AssetBindingRow.status,
        AssetBindingRow.removed_at,
        AssetBindingRow.metadata_json,
        AssetBindingRow.created_at,
    )


def _catalog_values(catalog: AssetCatalogRecordV2) -> dict[str, object]:
    return {
        "catalog_id": catalog.catalog_id,
        "catalog_key": catalog.catalog_key,
        "catalog_version": catalog.catalog_version,
        "source_type": catalog.source_type,
        "manifest_sha256": catalog.manifest_sha256,
        "archive_url": catalog.archive_url,
        "archive_sha256": catalog.archive_sha256,
        "license_manifest_json": _json(catalog.license_manifest),
        "status": catalog.status,
        "is_current": catalog.is_current,
        "progress_current": catalog.progress_current,
        "progress_total": catalog.progress_total,
        "installed_at": catalog.installed_at,
        "last_error_code": catalog.last_error_code,
        "last_error_message": catalog.last_error_message,
        "created_at": catalog.created_at,
        "updated_at": catalog.updated_at,
    }


def _catalog_from_row(row: RowMapping) -> AssetCatalogRecordV2:
    return AssetCatalogRecordV2(
        catalog_id=str(row["catalog_id"]),
        catalog_key=str(row["catalog_key"]),
        catalog_version=str(row["catalog_version"]),
        source_type=str(row["source_type"]),
        manifest_sha256=str(row["manifest_sha256"]),
        archive_url=str(row["archive_url"]),
        archive_sha256=str(row["archive_sha256"]),
        license_manifest=_json_object(str(row["license_manifest_json"])),
        status=str(row["status"]),
        is_current=bool(row["is_current"]),
        progress_current=int(row["progress_current"]),
        progress_total=int(row["progress_total"]),
        installed_at=_optional_string(row["installed_at"]),
        last_error_code=_optional_string(row["last_error_code"]),
        last_error_message=_optional_string(row["last_error_message"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _entity_summary_from_row(row: RowMapping) -> AssetLibraryEntitySummaryV2:
    return AssetLibraryEntitySummaryV2(
        entity_id=str(row["entity_id"]),
        scope=cast(AssetEntityScopeV2, str(row["scope"])),
        entity_type=str(row["entity_type"]),
        library_category=str(row["library_category"]),
        display_name=str(row["display_name"]),
        description=str(row["description"]),
        tags=tuple(_json_list(str(row["tags_json"]))),
        is_favorite=bool(row["is_favorite"]),
        status=cast(AssetEntityStatusV2, str(row["status"])),
        catalog_id=_optional_string(row["catalog_id"]),
        derived_from_entity_id=_optional_string(row["derived_from_entity_id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        deleted_at=_optional_string(row["deleted_at"]),
    )


def _version_from_row(row: RowMapping) -> AssetVersionMetadataV2:
    quality_json = _optional_string(row["quality_json"])
    return AssetVersionMetadataV2(
        version_id=str(row["version_id"]),
        asset_id=str(row["asset_id"]),
        version_no=int(row["version_no"]),
        storage_key=str(row["storage_key"]),
        sha256=str(row["sha256"]),
        size_bytes=int(row["size_bytes"]),
        mime_type=str(row["mime_type"]),
        width=_optional_int(row["width"]),
        height=_optional_int(row["height"]),
        duration_seconds=_optional_float(row["duration_seconds"]),
        prompt=_optional_string(row["prompt"]),
        provider=_optional_string(row["provider"]),
        model_id=_optional_string(row["model_id"]),
        source_workflow_id=_optional_string(row["source_workflow_id"]),
        source_node_id=_optional_string(row["source_node_id"]),
        source_item_id=_optional_string(row["source_item_id"]),
        source_slot_id=_optional_string(row["source_slot_id"]),
        parent_version_id=_optional_string(row["parent_version_id"]),
        quality=_json_object(quality_json) if quality_json is not None else None,
        metadata=_json_object(str(row["metadata_json"])),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
    )


def _binding_from_row(row: RowMapping) -> AssetBindingV2:
    return AssetBindingV2(
        binding_id=str(row["binding_id"]),
        selection_group_id=str(row["selection_group_id"]),
        binding_type=str(row["binding_type"]),
        workflow_id=str(row["workflow_id"]),
        target_node_id=_optional_string(row["target_node_id"]),
        target_item_id=_optional_string(row["target_item_id"]),
        target_slot_id=_optional_string(row["target_slot_id"]),
        source_entity_id=_optional_string(row["source_entity_id"]),
        asset_id=str(row["asset_id"]),
        version_id=str(row["version_id"]),
        reference_role=_optional_string(row["reference_role"]),
        use_as_prompt=bool(row["use_as_prompt"]),
        sort_order=int(row["sort_order"]),
        status=str(row["status"]),
        removed_at=_optional_string(row["removed_at"]),
        metadata=_json_object(str(row["metadata_json"])),
        created_at=str(row["created_at"]),
    )


def _require_user_entity(row: RowMapping) -> None:
    if row["scope"] != "user":
        raise V2PersistenceError(
            "asset_library_entity_read_only",
            "Recommended asset entities are read-only.",
            stage="asset_library_repository",
        )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_object(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise V2PersistenceError(
            "asset_library_metadata_invalid",
            "Asset library metadata is invalid.",
            stage="asset_library_repository",
        )
    return parsed


def _json_list(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise V2PersistenceError(
            "asset_library_metadata_invalid",
            "Asset library metadata is invalid.",
            stage="asset_library_repository",
        )
    return parsed


def _encode_cursor(updated_at: str, entity_id: str) -> str:
    payload = json.dumps([updated_at, entity_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise ValueError
        return value[0], value[1]
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise V2PersistenceError(
            "asset_library_cursor_invalid",
            "Asset library cursor is invalid.",
            stage="asset_library_repository",
        ) from error


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persistence_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_asset_library_persistence_failed",
        "V2 asset library persistence failed.",
        stage="asset_library_repository",
    )


def _catalog_not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "asset_catalog_not_found",
        "Asset catalog was not found.",
        stage="asset_library_repository",
    )


def _catalog_conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "asset_catalog_conflict",
        "Asset catalog conflicts with existing metadata.",
        stage="asset_library_repository",
    )


def _entity_not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "asset_library_entity_not_found",
        "Asset library entity was not found.",
        stage="asset_library_repository",
    )


def _entity_conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "asset_library_entity_conflict",
        "Asset library entity conflicts with existing metadata.",
        stage="asset_library_repository",
    )


def _asset_version_conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "asset_version_conflict",
        "Asset version conflicts with immutable metadata.",
        stage="asset_library_repository",
    )


def _binding_conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "asset_binding_conflict",
        "Asset binding conflicts with existing metadata.",
        stage="asset_library_repository",
    )
