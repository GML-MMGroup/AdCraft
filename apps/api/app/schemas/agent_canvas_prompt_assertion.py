"""Frozen evidence contracts for canonical prompt assertion policy."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_SHA256 = r"^sha256:[a-f0-9]{64}$"
_HEX_SHA256 = r"^[a-f0-9]{64}$"


class _PromptAssertionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PromptAssertionSourceSnapshotV1(_PromptAssertionModel):
    schema_version: Literal["1"] = "1"
    source_kind: Literal["binding", "document", "sequence"]
    binding_id: str | None = Field(default=None, min_length=1, max_length=160)
    binding_revision: int | None = Field(default=None, ge=1)
    source_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_node_revision: int | None = Field(default=None, ge=1)
    asset_id: str | None = Field(default=None, min_length=1, max_length=160)
    asset_version_id: str | None = Field(default=None, min_length=1, max_length=160)
    reference_purpose: str | None = Field(default=None, min_length=1, max_length=80)
    document_id: str | None = Field(default=None, min_length=1, max_length=160)
    document_revision: int | None = Field(default=None, ge=1)
    sequence_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_identity(self) -> "PromptAssertionSourceSnapshotV1":
        if (self.asset_id is None) != (self.asset_version_id is None):
            raise ValueError("Assertion Asset and version identities must be supplied together.")
        if self.source_kind == "binding" and (
            self.binding_id is None
            or self.binding_revision is None
            or self.reference_purpose is None
        ):
            raise ValueError("Binding assertion sources require exact Binding identity.")
        if self.source_kind == "document" and (
            self.document_id is None or self.document_revision is None
        ):
            raise ValueError("Document assertion sources require exact document identity.")
        if self.source_kind == "sequence" and self.sequence_id is None:
            raise ValueError("Sequence assertion sources require an exact sequence identity.")
        return self


class PromptAssertionEvidenceV1(_PromptAssertionModel):
    schema_version: Literal["1"] = "1"
    policy_ref: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(min_length=1, max_length=32)
    policy_digest: str = Field(pattern=_SHA256)
    recipe_id: str = Field(min_length=1, max_length=160)
    recipe_version: str = Field(min_length=1, max_length=32)
    assertion_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    assertion_block_digest: str = Field(pattern=_SHA256)
    prepared_prompt_digest: str = Field(pattern=_HEX_SHA256)
    source_snapshots: tuple[PromptAssertionSourceSnapshotV1, ...] = Field(default=(), max_length=64)
    document_revisions: dict[str, int] = Field(default_factory=dict, max_length=16)
    sequence_id: str | None = Field(default=None, min_length=1, max_length=160)
    character_identity_projection_digest: str | None = Field(default=None, pattern=_SHA256)
    scene_environment_projection_digest: str | None = Field(default=None, pattern=_SHA256)
    engine_owned_fields_digest: str = Field(pattern=_SHA256)
    evidence_digest: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def validate_canonical_identity(self) -> "PromptAssertionEvidenceV1":
        if len(self.assertion_ids) != len(set(self.assertion_ids)):
            raise ValueError("Prompt assertion IDs must be unique.")
        if self.evidence_digest != prompt_assertion_evidence_digest(self):
            raise ValueError("Prompt assertion evidence digest does not match its payload.")
        return self

    @classmethod
    def build(cls, **values: object) -> "PromptAssertionEvidenceV1":
        payload = {"schema_version": "1", **values}
        # Include newly additive nullable identity fields in the pre-validation
        # digest so legacy callers and validated model dumps share one canonical
        # representation.
        payload.setdefault("character_identity_projection_digest", None)
        payload.setdefault("scene_environment_projection_digest", None)
        return cls.model_validate({**payload, "evidence_digest": _prefixed_digest(payload)})


class ProviderPromptAssertionEvidenceV1(_PromptAssertionModel):
    schema_version: Literal["1"] = "1"
    policy_ref: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(min_length=1, max_length=32)
    policy_digest: str = Field(pattern=_SHA256)
    recipe_id: str = Field(min_length=1, max_length=160)
    recipe_version: str = Field(min_length=1, max_length=32)
    assertion_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    preparation_evidence_digest: str = Field(pattern=_SHA256)
    assertion_block_digest: str = Field(pattern=_SHA256)
    prepared_prompt_digest: str = Field(pattern=_HEX_SHA256)
    provider_prompt_digest: str = Field(pattern=_HEX_SHA256)


def prompt_assertion_evidence_digest(evidence: PromptAssertionEvidenceV1) -> str:
    return _prefixed_digest(evidence.model_dump(mode="json", exclude={"evidence_digest"}))


def safe_prompt_assertion_metadata(
    evidence: PromptAssertionEvidenceV1,
) -> dict[str, object]:
    """Project stable prompt-policy identity without creative or source content."""

    metadata: dict[str, object] = {
        "prompt_assertion_policy_ref": evidence.policy_ref,
        "prompt_assertion_policy_digest": evidence.policy_digest,
        "prompt_assertion_assertion_ids": list(evidence.assertion_ids),
        "prompt_assertion_evidence_digest": evidence.evidence_digest,
        "prompt_assertion_block_digest": evidence.assertion_block_digest,
    }
    if evidence.character_identity_projection_digest is not None:
        metadata["prompt_character_identity_projection_digest"] = (
            evidence.character_identity_projection_digest
        )
    if evidence.scene_environment_projection_digest is not None:
        metadata["prompt_scene_environment_projection_digest"] = (
            evidence.scene_environment_projection_digest
        )
    return metadata


def safe_provider_prompt_assertion_metadata(
    evidence: ProviderPromptAssertionEvidenceV1,
) -> dict[str, object]:
    """Project stable provider-prompt linkage without prompt or source content."""

    return {
        "prompt_assertion_policy_ref": evidence.policy_ref,
        "prompt_assertion_policy_digest": evidence.policy_digest,
        "prompt_assertion_assertion_ids": list(evidence.assertion_ids),
        "prompt_assertion_evidence_digest": evidence.preparation_evidence_digest,
        "prompt_assertion_block_digest": evidence.assertion_block_digest,
        "provider_prompt_digest": evidence.provider_prompt_digest,
    }


def _prefixed_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=lambda item: item.model_dump(mode="json"),
    )
    return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"
