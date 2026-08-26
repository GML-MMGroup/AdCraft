"""Strict typed contracts for guided Product source input commits."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas import CanvasNodeV2, ProjectAssetSummaryV2


class _GuidedProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GuidedProductAssetVersionRefV1(_GuidedProductModel):
    asset_id: str = Field(min_length=1, max_length=160)
    version_id: str = Field(min_length=1, max_length=160)


class GuidedProductInputCommitRequestV1(_GuidedProductModel):
    input_kind: Literal["main", "multiview"]
    asset_versions: tuple[GuidedProductAssetVersionRefV1, ...] = Field(
        min_length=1,
        max_length=8,
    )
    interaction_id: str = Field(min_length=1, max_length=160)
    expected_interaction_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    expected_guidance_revision: int = Field(ge=1)
    pending_handoff_id: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_cardinality(self) -> "GuidedProductInputCommitRequestV1":
        expected = 1 if self.input_kind == "main" else range(2, 9)
        valid = (
            len(self.asset_versions) == expected
            if isinstance(expected, int)
            else len(self.asset_versions) in expected
        )
        if not valid:
            raise ValueError(
                "main requires exactly one asset version and multiview requires two to eight."
            )
        identities = [(item.asset_id, item.version_id) for item in self.asset_versions]
        if len(identities) != len(set(identities)):
            raise ValueError("Product input asset versions must be unique.")
        return self


class ProductUploadInputProvenanceV1(_GuidedProductModel):
    asset_id: str = Field(min_length=1, max_length=160)
    version_id: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    order: int = Field(ge=0, le=7)


class ProductUploadCompilationProvenanceV1(_GuidedProductModel):
    kind: Literal["upload_compilation"] = "upload_compilation"
    profile_id: Literal["product-upload-multiview-v1"]
    profile_version: int = Field(ge=1)
    ordered_inputs: tuple[ProductUploadInputProvenanceV1, ...] = Field(
        min_length=2,
        max_length=8,
    )
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    compiler_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_order(self) -> "ProductUploadCompilationProvenanceV1":
        if tuple(item.order for item in self.ordered_inputs) != tuple(
            range(len(self.ordered_inputs))
        ):
            raise ValueError("Product upload provenance order must be contiguous.")
        return self


class GuidedProductInputCommitReceiptV1(_GuidedProductModel):
    operation_id: str = Field(min_length=1, max_length=160)
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    workflow_id: str = Field(min_length=1, max_length=160)
    input_kind: Literal["main", "multiview"]
    node_id: str = Field(min_length=1, max_length=160)
    asset_id: str = Field(min_length=1, max_length=160)
    version_id: str = Field(min_length=1, max_length=160)
    compiled_asset_id: str | None = Field(default=None, max_length=160)
    compiled_version_id: str | None = Field(default=None, max_length=160)
    provenance_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    workflow_revision: int = Field(ge=1)
    guidance_revision: int = Field(ge=1)
    events_cursor: int = Field(ge=0)
    committed_at: datetime


class GuidedProductInputCommitResponseV1(_GuidedProductModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    guidance_revision: int = Field(ge=1)
    input_kind: Literal["main", "multiview"]
    node: CanvasNodeV2
    compiled_asset: ProjectAssetSummaryV2 | None = None
    receipt: GuidedProductInputCommitReceiptV1
    replayed: bool = False
    events_cursor: int = Field(ge=0)


class GuidedProductSourceActionV1(_GuidedProductModel):
    input_kind: Literal["main", "multiview"]
    choice: Literal["upload", "generate"]
    handoff_mode: Literal["pending", "apply"] = "apply"
    asset_versions: tuple[GuidedProductAssetVersionRefV1, ...] = Field(
        default=(),
        max_length=8,
    )
    pending_handoff_id: str | None = Field(default=None, max_length=160)
    expected_guidance_revision: int = Field(ge=1)
    question_id: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_handoff(self) -> "GuidedProductSourceActionV1":
        if self.choice == "generate":
            if self.handoff_mode != "apply" or self.asset_versions or self.pending_handoff_id:
                raise ValueError("Generate Product source actions cannot carry upload handoffs.")
            return self
        if not self.asset_versions:
            raise ValueError("Upload Product source actions require AssetVersion references.")
        expected = 1 if self.input_kind == "main" else range(2, 9)
        valid = (
            len(self.asset_versions) == expected
            if isinstance(expected, int)
            else len(self.asset_versions) in expected
        )
        if not valid:
            raise ValueError(
                "main upload requires one asset version and multiview upload requires two to eight."
            )
        identities = [(item.asset_id, item.version_id) for item in self.asset_versions]
        if len(identities) != len(set(identities)):
            raise ValueError("Product source upload asset versions must be unique.")
        if self.handoff_mode == "pending" and self.pending_handoff_id is not None:
            raise ValueError("Pending Product source actions cannot consume a handoff.")
        return self


GuidedProductSourceAction = Annotated[
    GuidedProductSourceActionV1,
    Field(discriminator="input_kind"),
]
