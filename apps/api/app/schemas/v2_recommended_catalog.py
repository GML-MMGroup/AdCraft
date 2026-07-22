"""Strict, shared contracts for immutable Recommended Assets packages."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class CatalogModel(BaseModel):
    """Package JSON must be complete and portable across installations."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CatalogMediaDeclarationV1(CatalogModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: Literal["image/png", "image/jpeg"]
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if not value or value.startswith("/") or "\\" in value:
            raise ValueError("catalog media paths must be safe relative POSIX paths")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("catalog media paths must be safe relative POSIX paths")
        return value


class CatalogMemberV1(CatalogModel):
    member_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    semantic_type: Literal["character_three_view", "scene_multi_view_grid"]
    is_primary: Literal[True]
    is_default_reference: Literal[True]
    sort_order: Literal[0]
    original: CatalogMediaDeclarationV1
    preview: CatalogMediaDeclarationV1


class CatalogEntityV1(CatalogModel):
    entity_id: str = Field(min_length=1)
    entity_type: Literal["character", "scene"]
    library_category: Literal["characters", "scenes"]
    display_name: str = Field(min_length=1)
    description: str = ""
    tags: tuple[str, ...] = ()
    members: tuple[CatalogMemberV1, ...] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def validate_member_kind(self) -> "CatalogEntityV1":
        member = self.members[0]
        expected = (
            "character_three_view" if self.entity_type == "character" else "scene_multi_view_grid"
        )
        if member.semantic_type != expected:
            raise ValueError("catalog member semantic type does not match its entity")
        return self


class CatalogBuildMetadataV1(CatalogModel):
    builder: Literal["adcraft-recommended-assets-builder"]
    pillow_version: str = Field(min_length=1)
    character_count: int = Field(ge=0)
    scene_count: int = Field(ge=0)


class CatalogManifestV1(CatalogModel):
    schema_version: Literal[1]
    catalog_key: Literal["adcraft-recommended-assets-v1"]
    catalog_version: str
    display_name: Literal["AdCraft Recommended Assets"]
    license_manifest_path: Literal["LICENSES.json"]
    source_url: str
    build: CatalogBuildMetadataV1
    entities: tuple[CatalogEntityV1, ...] = Field(min_length=1)

    @field_validator("catalog_version")
    @classmethod
    def validate_catalog_version(cls, value: str) -> str:
        if not _SEMVER.fullmatch(value):
            raise ValueError("catalog version must use major.minor.patch")
        return value

    @model_validator(mode="after")
    def validate_unique_package_graph(self) -> "CatalogManifestV1":
        members = [member for entity in self.entities for member in entity.members]
        for values, label in (
            ([entity.entity_id for entity in self.entities], "entity IDs"),
            ([member.member_id for member in members], "member IDs"),
            ([member.asset_id for member in members], "asset IDs"),
            ([member.version_id for member in members], "version IDs"),
            ([member.original.path for member in members], "original paths"),
            ([member.preview.path for member in members], "preview paths"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"catalog {label} must be unique")
        return self


class CatalogLicenseEntryV1(CatalogModel):
    license_id: Literal["CC0-1.0"]
    name: Literal["CC0 1.0 Universal"]
    canonical_url: Literal["https://creativecommons.org/publicdomain/zero/1.0/"]
    attribution_required: Literal[False]
    attribution: str
    source_statement: str


class CatalogLicenseManifestV1(CatalogModel):
    schema_version: Literal[1]
    licenses: tuple[CatalogLicenseEntryV1, ...] = Field(min_length=1)
