"""Minimal user-owned entity creation over immutable V2 asset versions."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_asset_library import (
    AssetEntityCreate,
    AssetEntityMemberCreate,
    AssetLibraryEntityDetailV2,
    CreateAssetLibraryEntityRequestV2,
)
from app.services.v2_data_boundary import V2DataBoundaryError, validate_v2_data_path


class V2AssetLibraryError(Exception):
    """A stable domain failure for user entity creation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class V2AssetLibraryService:
    """Create user entities without copying bytes or mutating source versions."""

    def __init__(self, *, data_dir: Path, repository: V2AssetLibraryRepository) -> None:
        self._data_dir = data_dir
        self._repository = repository

    def create_entity(
        self,
        request: CreateAssetLibraryEntityRequestV2,
    ) -> AssetLibraryEntityDetailV2:
        """Create a user entity from selected versions or one recommended source."""

        category = _category_for_entity(request.entity_type, request.library_category)
        if request.source.type == "recommended_entity":
            return self._fork_recommended_entity(request, category)
        return self._create_from_selected_versions(request, category)

    def _fork_recommended_entity(
        self,
        request: CreateAssetLibraryEntityRequestV2,
        category: str,
    ) -> AssetLibraryEntityDetailV2:
        try:
            source = self._repository.get_entity(request.source.entity_id)
        except V2PersistenceError as error:
            raise _library_error_from_persistence(error) from error
        if source.scope != "recommended":
            raise V2AssetLibraryError(
                "asset_library_source_invalid", "Asset library source is invalid."
            )
        if source.entity_type != request.entity_type:
            raise V2AssetLibraryError(
                "asset_library_source_invalid", "Asset library source is invalid."
            )
        self._require_available_members(source.members)
        members = tuple(
            AssetEntityMemberCreate(
                member_id=_new_id("amem"),
                asset_id=member.asset_id,
                version_id=member.version_id,
                semantic_type=member.semantic_type,
                is_primary=member.is_primary,
                is_default_reference=member.is_default_reference,
                sort_order=member.sort_order,
            )
            for member in source.members
        )
        return self._create_user_entity(
            request,
            category=category,
            members=members,
            derived_from_entity_id=source.entity_id,
        )

    def _create_from_selected_versions(
        self,
        request: CreateAssetLibraryEntityRequestV2,
        category: str,
    ) -> AssetLibraryEntityDetailV2:
        source_members = request.source.members
        try:
            versions = self._repository.resolve_versions(
                tuple(member.version_id for member in source_members)
            )
        except V2PersistenceError as error:
            raise _library_error_from_persistence(error) from error
        versions_by_id = {version.version_id: version for version in versions}
        if len(versions_by_id) != len(source_members):
            raise V2AssetLibraryError("asset_version_not_found", "Asset version was not found.")
        members: list[AssetEntityMemberCreate] = []
        for sort_order, selection in enumerate(source_members):
            version = versions_by_id[selection.version_id]
            if version.asset_id != selection.asset_id:
                raise V2AssetLibraryError(
                    "asset_library_source_invalid",
                    "Asset version does not match the selected asset.",
                )
            self._require_available_version(version.storage_key)
            members.append(
                AssetEntityMemberCreate(
                    member_id=_new_id("amem"),
                    asset_id=selection.asset_id,
                    version_id=selection.version_id,
                    semantic_type=selection.semantic_type,
                    is_primary=selection.is_primary,
                    is_default_reference=selection.is_default_reference,
                    sort_order=sort_order,
                )
            )
        return self._create_user_entity(request, category=category, members=tuple(members))

    def _create_user_entity(
        self,
        request: CreateAssetLibraryEntityRequestV2,
        *,
        category: str,
        members: tuple[AssetEntityMemberCreate, ...],
        derived_from_entity_id: str | None = None,
    ) -> AssetLibraryEntityDetailV2:
        try:
            return self._repository.create_entity(
                AssetEntityCreate(
                    entity_id=_new_id("aent"),
                    scope="user",
                    entity_type=request.entity_type,
                    library_category=category,
                    display_name=request.display_name,
                    description=request.description,
                    tags=request.tags,
                    derived_from_entity_id=derived_from_entity_id,
                ),
                members=members,
            )
        except V2PersistenceError as error:
            raise _library_error_from_persistence(error) from error

    def _require_available_members(self, members: tuple[object, ...]) -> None:
        for member in members:
            version = getattr(member, "version", None)
            if version is None:
                raise V2AssetLibraryError(
                    "asset_content_unavailable", "Asset content is unavailable."
                )
            self._require_available_version(version.storage_key)

    def _require_available_version(self, storage_key: str) -> None:
        try:
            path = validate_v2_data_path(
                self._data_dir,
                storage_key,
                operation="v2-asset-library-create-entity",
            )
        except V2DataBoundaryError as error:
            raise V2AssetLibraryError(
                "asset_content_unavailable", "Asset content is unavailable."
            ) from error
        if not path.is_file():
            raise V2AssetLibraryError("asset_content_unavailable", "Asset content is unavailable.")


def _category_for_entity(entity_type: str, requested_category: str) -> str:
    expected = {
        "product": "props",
        "prop": "props",
        "character": "characters",
        "scene": "scenes",
    }.get(entity_type)
    if expected is not None and requested_category != expected:
        raise V2AssetLibraryError(
            "asset_library_category_invalid",
            "Asset library category is invalid for the entity type.",
        )
    return requested_category


def _library_error_from_persistence(error: V2PersistenceError) -> V2AssetLibraryError:
    code = "asset_version_not_found" if error.code == "asset_version_not_found" else error.code
    return V2AssetLibraryError(code, str(error))


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"
