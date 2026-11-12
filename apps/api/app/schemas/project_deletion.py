"""Internal, durable cleanup manifest for a permanently deleted Project."""

from pydantic import BaseModel, ConfigDict


class ProjectDeletionManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    workflow_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    storage_keys: tuple[str, ...]
