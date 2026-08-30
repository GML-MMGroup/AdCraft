"""Strict public contracts for V2 project records."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProjectStatusV2 = Literal["active", "archived", "trashed"]


class ProjectCoverV2(BaseModel):
    """Immutable AssetVersion identity and browser-safe preview metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    media_type: Literal["image", "video"]
    preview_url: str | None = None
    poster_url: str | None = None


class ProjectCreate(BaseModel):
    """Internal immutable input for the initial Project transaction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    status: ProjectStatusV2 = "active"
    is_favorite: bool = False
    cover_asset_id: str | None = None
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class ProjectRecord(BaseModel):
    """Internal durable Project record without the Workflow join."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    status: ProjectStatusV2
    is_favorite: bool
    cover_asset_id: str | None = None
    project_version: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    deleted_at: str | None = None


class ProjectRecordPage(BaseModel):
    """Internal deterministic page of Project records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[ProjectRecord, ...] = ()
    next_cursor: str | None = None


class ProjectCatalogRecord(ProjectRecord):
    """Internal Project record joined to its owning Agent Canvas Workflow."""

    workflow_id: str = Field(min_length=1)


class ProjectCatalogRecordPage(BaseModel):
    """Internal deterministic page of joined Project catalog records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[ProjectCatalogRecord, ...] = ()
    next_cursor: str | None = None


class ProjectV2(BaseModel):
    """The durable Project envelope that owns exactly one V2 Workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    status: ProjectStatusV2 = "active"
    is_favorite: bool = False
    cover_asset_id: str | None = None
    project_version: int = Field(ge=1)
    semantic_revision_no: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    deleted_at: str | None = None


class ProjectV2Summary(BaseModel):
    """Bounded Project data for catalog listings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: ProjectStatusV2
    is_favorite: bool
    cover_asset_id: str | None = None
    cover: ProjectCoverV2 | None = None
    project_version: int = Field(ge=1)
    updated_at: str = Field(min_length=1)


class ProjectV2ListResponse(BaseModel):
    """Cursor-paginated Project catalog response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[ProjectV2Summary, ...] = ()
    next_cursor: str | None = None


class ProjectV2UpdateRequest(BaseModel):
    """Permitted Project catalog edits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    is_favorite: bool | None = None
    cover_asset_id: str | None = None
    status: Literal["active", "archived"] | None = None
