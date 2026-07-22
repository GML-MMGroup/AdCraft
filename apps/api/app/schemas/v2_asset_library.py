"""Strict contracts for the V2 unified asset library persistence boundary."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


AssetLibraryScopeV2 = Literal["my", "recommended"]
AssetEntityScopeV2 = Literal["user", "recommended"]
AssetLibraryCategoryV2 = Literal["characters", "scenes", "props"]
AssetEntityTypeV2 = Literal["product", "character", "scene", "prop", "generic"]
AssetMediaTypeV2 = Literal["image", "video", "audio", "text"]
AssetSourceTypeV2 = Literal["recommended", "upload", "generated", "derived"]
AssetCatalogInstallStatusV2 = Literal[
    "not_installed", "downloading", "verifying", "installing", "ready", "failed"
]
AssetEntityStatusV2 = Literal["active", "trashed"]
AssetVersionStatusV2 = Literal["ready", "unavailable"]
AssetBindingStatusV2 = Literal["active", "removed"]


class _AssetLibraryModel(BaseModel):
    """Base model that rejects unversioned or unexpected asset-library input."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AssetCatalogRecordV2(_AssetLibraryModel):
    """Durable metadata for one pinned recommended catalog version."""

    catalog_id: str = Field(min_length=1)
    catalog_key: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    manifest_sha256: str = Field(min_length=1)
    archive_url: str = Field(min_length=1)
    archive_sha256: str = Field(min_length=1)
    license_manifest: dict[str, JsonValue] = Field(default_factory=dict)
    status: AssetCatalogInstallStatusV2
    is_current: bool = False
    progress_current: int = Field(default=0, ge=0)
    progress_total: int = Field(default=0, ge=0)
    installed_at: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class AssetRecordCreate(_AssetLibraryModel):
    """A logical asset identity independent from its physical bytes."""

    asset_id: str = Field(min_length=1)
    media_type: AssetMediaTypeV2
    source_type: AssetSourceTypeV2
    display_name: str = Field(min_length=1)
    status: Literal["active", "unavailable"] = "active"
    created_at: str | None = None
    updated_at: str | None = None


class AssetVersionCreate(_AssetLibraryModel):
    """One immutable version of a logical asset."""

    version_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    version_no: int | None = Field(default=None, ge=1)
    storage_key: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    mime_type: str = Field(min_length=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    duration_seconds: float | None = Field(default=None, ge=0)
    prompt: str | None = None
    provider: str | None = None
    model_id: str | None = None
    source_workflow_id: str | None = None
    source_node_id: str | None = None
    source_item_id: str | None = None
    source_slot_id: str | None = None
    parent_version_id: str | None = None
    quality: dict[str, JsonValue] | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    status: AssetVersionStatusV2 = "ready"
    created_at: str | None = None


class AssetVersionMetadataV2(_AssetLibraryModel):
    """Immutable version metadata returned by repository reads."""

    version_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    version_no: int = Field(ge=1)
    storage_key: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    mime_type: str = Field(min_length=1)
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    prompt: str | None = None
    provider: str | None = None
    model_id: str | None = None
    source_workflow_id: str | None = None
    source_node_id: str | None = None
    source_item_id: str | None = None
    source_slot_id: str | None = None
    parent_version_id: str | None = None
    quality: dict[str, JsonValue] | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    status: AssetVersionStatusV2
    created_at: str = Field(min_length=1)


class AssetEntityCreate(_AssetLibraryModel):
    """Create one reusable entity without changing its member versions."""

    entity_id: str = Field(min_length=1)
    scope: AssetEntityScopeV2
    entity_type: AssetEntityTypeV2
    library_category: AssetLibraryCategoryV2
    display_name: str = Field(min_length=1)
    description: str = ""
    tags: tuple[str, ...] = ()
    is_favorite: bool = False
    catalog_id: str | None = None
    derived_from_entity_id: str | None = None
    status: AssetEntityStatusV2 = "active"
    deleted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AssetEntityMemberCreate(_AssetLibraryModel):
    """Pin an entity member to one immutable asset version."""

    member_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)
    is_primary: bool = False
    is_default_reference: bool = False
    sort_order: int = Field(ge=0)
    created_at: str | None = None


class AssetEntityMemberV2(_AssetLibraryModel):
    """Ordered immutable member metadata for one reusable entity."""

    member_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)
    is_primary: bool
    is_default_reference: bool
    sort_order: int = Field(ge=0)
    created_at: str = Field(min_length=1)
    version: AssetVersionMetadataV2 | None = None


class AssetLibraryEntitySummaryV2(_AssetLibraryModel):
    """Bounded entity data for library list results."""

    entity_id: str = Field(min_length=1)
    scope: AssetEntityScopeV2
    entity_type: AssetEntityTypeV2
    library_category: AssetLibraryCategoryV2
    display_name: str = Field(min_length=1)
    description: str
    tags: tuple[str, ...] = ()
    is_favorite: bool
    status: AssetEntityStatusV2
    catalog_id: str | None = None
    derived_from_entity_id: str | None = None
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    deleted_at: str | None = None


class AssetLibraryEntityDetailV2(AssetLibraryEntitySummaryV2):
    """Entity metadata with ordered version-pinned members."""

    members: tuple[AssetEntityMemberV2, ...] = ()


class AssetLibraryEntityPageV2(_AssetLibraryModel):
    """Internal deterministic page returned by the repository."""

    items: tuple[AssetLibraryEntitySummaryV2, ...] = ()
    next_cursor: str | None = None


class AssetBindingCreate(_AssetLibraryModel):
    """Create one version-pinned workflow reference binding."""

    binding_id: str = Field(min_length=1)
    selection_group_id: str = Field(min_length=1)
    binding_type: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    target_node_id: str | None = None
    target_item_id: str | None = None
    target_slot_id: str | None = None
    source_entity_id: str | None = None
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    reference_role: str | None = None
    use_as_prompt: bool = True
    sort_order: int = Field(ge=0)
    status: AssetBindingStatusV2 = "active"
    removed_at: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: str | None = None


class AssetBindingV2(AssetBindingCreate):
    """Persisted reference binding view."""

    created_at: str = Field(min_length=1)


class UpdateAssetLibraryEntityRequestV2(_AssetLibraryModel):
    """Permitted mutable metadata for a user-owned entity."""

    display_name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    tags: tuple[str, ...] | None = None
    is_favorite: bool | None = None


class AssetEntityMembersSourceV2(_AssetLibraryModel):
    """Create a user entity from explicitly selected immutable members."""

    type: Literal["members"] = "members"
    members: tuple["AssetVersionEntityMemberSelectionV2", ...] = Field(min_length=1)


class AssetVersionEntityMemberSelectionV2(_AssetLibraryModel):
    """Public selection of one existing immutable version for a new entity."""

    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)
    is_primary: bool = False
    is_default_reference: bool = False


class RecommendedEntitySourceV2(_AssetLibraryModel):
    """Create a user-owned fork from a recommended entity."""

    type: Literal["recommended_entity"] = "recommended_entity"
    entity_id: str = Field(min_length=1)


AssetEntitySourceV2 = Annotated[
    AssetEntityMembersSourceV2 | RecommendedEntitySourceV2,
    Field(discriminator="type"),
]


class CreateAssetLibraryEntityRequestV2(_AssetLibraryModel):
    """Public create contract retained for the later API batch."""

    display_name: str = Field(min_length=1)
    entity_type: AssetEntityTypeV2
    library_category: AssetLibraryCategoryV2
    description: str = ""
    tags: tuple[str, ...] = ()
    source: AssetEntitySourceV2


class AssetVersionReferenceSelectionV2(_AssetLibraryModel):
    """Select exactly one immutable asset version for a slot binding."""

    selection_type: Literal["asset_version"] = "asset_version"
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)


class AssetEntityReferenceSelectionV2(_AssetLibraryModel):
    """Select all default members of one reusable entity."""

    selection_type: Literal["entity"] = "entity"
    entity_id: str = Field(min_length=1)


ReferenceSelectionV2 = Annotated[
    AssetVersionReferenceSelectionV2 | AssetEntityReferenceSelectionV2,
    Field(discriminator="selection_type"),
]


class AttachReferenceSelectionsRequestV2(_AssetLibraryModel):
    """Public request contract for the later atomic binding API."""

    selections: tuple[ReferenceSelectionV2, ...] = Field(min_length=1)
    reference_role: str | None = None
    use_as_prompt: bool = True


class AssetLibraryListResponseV2(_AssetLibraryModel):
    """Public list response for the future asset-library route."""

    entities: tuple[AssetLibraryEntitySummaryV2, ...] = ()
    next_cursor: str | None = None
    catalog_status: AssetCatalogInstallStatusV2 | None = None


class AssetLibraryMemberResponseV2(_AssetLibraryModel):
    """Frontend-safe immutable metadata for a selected entity member."""

    member_id: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    duration_seconds: float | None = Field(default=None, ge=0)
    public_url: str | None = None
    is_primary: bool
    is_default_reference: bool
    sort_order: int = Field(ge=0)


class AssetLibraryEntityResponseV2(_AssetLibraryModel):
    """Frontend-safe reusable asset entity summary."""

    entity_id: str = Field(min_length=1)
    scope: AssetEntityScopeV2
    entity_type: AssetEntityTypeV2
    library_category: AssetLibraryCategoryV2
    display_name: str = Field(min_length=1)
    description: str
    tags: tuple[str, ...] = ()
    is_favorite: bool
    status: AssetEntityStatusV2
    preview_member: AssetLibraryMemberResponseV2 | None = None
    member_count: int = Field(ge=0)


class AssetLibraryEntityDetailResponseV2(AssetLibraryEntityResponseV2):
    """One entity with its declared ordered immutable members."""

    members: tuple[AssetLibraryMemberResponseV2, ...] = ()
    catalog_source_url: str | None = None
    license_id: str | None = None
    attribution: str | None = None


class AssetLibraryEntityListResponseV2(_AssetLibraryModel):
    """Frontend-safe cursor page returned by the V2 asset-library route."""

    entities: tuple[AssetLibraryEntityResponseV2, ...] = ()
    next_cursor: str | None = None
    catalog_status: AssetCatalogInstallStatusV2 | None = None


class RecommendedCatalogStatusResponseV2(_AssetLibraryModel):
    """Public recommended-catalog install state."""

    catalog_key: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    status: AssetCatalogInstallStatusV2
    progress_current: int = Field(ge=0)
    progress_total: int = Field(ge=0)
    last_error_code: str | None = None
    message: str | None = None


class AssetMetadataImportItemResultV2(_AssetLibraryModel):
    """Bounded result for one legacy V2 asset metadata import attempt."""

    source_path: str = Field(min_length=1)
    record_kind: Literal["version", "relation"]
    status: Literal["imported", "quarantined"]
    asset_id: str | None = None
    version_id: str | None = None
    binding_id: str | None = None
    error_code: str | None = None
    validation_paths: tuple[str, ...] = ()


class AssetMetadataImportReportV2(_AssetLibraryModel):
    """Immutable aggregate for the one-time V2 JSON metadata import."""

    migration_name: str = Field(min_length=1)
    items: tuple[AssetMetadataImportItemResultV2, ...] = ()

    @property
    def imported_version_count(self) -> int:
        return sum(
            item.status == "imported" and item.record_kind == "version" for item in self.items
        )

    @property
    def imported_binding_count(self) -> int:
        return sum(
            item.status == "imported" and item.record_kind == "relation" for item in self.items
        )

    @property
    def quarantined_count(self) -> int:
        return sum(item.status == "quarantined" for item in self.items)
