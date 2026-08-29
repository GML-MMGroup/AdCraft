"""Private, deterministic identity facts for Storyboard selection lineage.

The public Proposal and interaction contracts intentionally remain unchanged.  This
module contains the small immutable value object used by the server-owned
Storyboard selection seam.  Client request aliases and operational retry data are
kept out of the value object by construction.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


StoryboardSelectionActionV1 = Literal[
    "select_option",
    "custom_direction",
    "delegate_choice",
    "reuse_direction",
]


class StoryboardSelectionIdentityV1(BaseModel):
    """Frozen authority tuple for one logical Storyboard selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_version: Literal["storyboard-selection-v1"] = "storyboard-selection-v1"
    workflow_id: str = Field(min_length=1, max_length=160)
    proposal_id: str = Field(min_length=1, max_length=160)
    proposal_revision: int = Field(ge=1)
    action: StoryboardSelectionActionV1
    selection_actor: Literal["user", "agent"]
    selected_option_id: str | None = Field(default=None, min_length=1, max_length=160)
    custom_text_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reference_plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_session_revision: int = Field(ge=1)
    stage_revision: int = Field(ge=1)
    target_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    target_node_revision: int | None = Field(default=None, ge=1)
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    character_phase: Literal["main", "turnaround"] | None = None
    requirement_revision_id: str | None = Field(default=None, min_length=1, max_length=160)
    requirement_revision_no: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_selection_value(self) -> "StoryboardSelectionIdentityV1":
        if self.action == "custom_direction":
            if self.selected_option_id is not None or self.custom_text_digest is None:
                raise ValueError("Custom Storyboard selections require a text digest only.")
        elif self.selected_option_id is None or self.custom_text_digest is not None:
            raise ValueError("Option Storyboard selections require one option ID only.")
        if (self.target_node_id is None) != (self.target_node_revision is None):
            raise ValueError("Target identity requires both node ID and revision.")
        if (self.occurrence_id is None) != (self.character_phase is None):
            raise ValueError("Occurrence identity requires occurrence and phase.")
        if (self.requirement_revision_id is None) != (self.requirement_revision_no is None):
            raise ValueError("Requirement identity requires revision ID and number.")
        return self

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return the exact bounded payload covered by the identity digest."""

        return self.model_dump(mode="json", exclude_none=True)

    @property
    def digest(self) -> str:
        """Return the stable SHA-256 digest of the canonical authority tuple."""

        serialized = json.dumps(
            self.canonical_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(serialized).hexdigest()


class StoryboardSelectionIdsV1(BaseModel):
    """Bounded deterministic IDs derived only from a selection identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    materialization_id: str = Field(min_length=1, max_length=160)
    envelope_id: str = Field(min_length=1, max_length=160)
    action_turn_id: str = Field(min_length=1, max_length=160)
    continuation_id: str = Field(min_length=1, max_length=160)
    request_identity: str = Field(min_length=1, max_length=256)


def derive_storyboard_selection_ids(
    identity: StoryboardSelectionIdentityV1,
) -> StoryboardSelectionIdsV1:
    """Derive all operational lineage IDs without client or retry inputs."""

    digest = identity.digest
    materialization_id = f"materialization_storyboard_{digest[:32]}"
    envelope_id = f"envelope_{_digest(materialization_id)[:32]}"
    continuation_id = f"continuation_{_digest(materialization_id)[:32]}"
    return StoryboardSelectionIdsV1(
        identity_digest=digest,
        materialization_id=materialization_id,
        envelope_id=envelope_id,
        action_turn_id=f"turn_storyboard_{digest[:32]}",
        continuation_id=continuation_id,
        request_identity=f"storyboard-selection:{digest}",
    )


def identity_digest_from_envelope(envelope: object) -> str | None:
    """Read the marker used on canonical envelopes, if present."""

    marker = getattr(envelope, "agent_request_identity", None)
    if marker is None:
        marker = getattr(envelope, "idempotency_identity", None)
    if not isinstance(marker, str) or not marker.startswith("storyboard-selection:"):
        return None
    digest = marker.removeprefix("storyboard-selection:")
    return digest if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest) else None


def identity_from_envelope(envelope: object) -> StoryboardSelectionIdentityV1 | None:
    """Reconstruct identity facts from an immutable canonical envelope."""

    if getattr(envelope, "capability_id", None) != "storyboard_design":
        return None
    if identity_digest_from_envelope(envelope) is None:
        return None
    selected_option = getattr(envelope, "selected_option", None)
    action = getattr(envelope, "action", None)
    custom_text = getattr(selected_option, "custom_text", None)
    custom_digest = (
        sha256(str(custom_text).encode("utf-8")).hexdigest()
        if action == "custom_direction" and custom_text
        else None
    )
    selected_option_id = (
        None if action == "custom_direction" else getattr(selected_option, "option_id", None)
    )
    return StoryboardSelectionIdentityV1(
        workflow_id=str(envelope.workflow_id),
        proposal_id=str(envelope.proposal_id),
        proposal_revision=int(envelope.proposal_revision),
        action=action,
        selection_actor=str(envelope.selection_actor),
        selected_option_id=selected_option_id,
        custom_text_digest=custom_digest,
        reference_plan_digest=str(envelope.reference_plan.digest),
        expected_session_revision=int(envelope.expected_session_revision),
        stage_revision=int(envelope.stage_revision),
        target_node_id=(
            str(envelope.target_node_id) if envelope.target_node_id is not None else None
        ),
        target_node_revision=(
            int(envelope.target_node_revision)
            if envelope.target_node_revision is not None
            else None
        ),
        occurrence_id=(str(envelope.occurrence_id) if envelope.occurrence_id is not None else None),
        character_phase=(
            str(envelope.character_phase) if envelope.character_phase is not None else None
        ),
        requirement_revision_id=(
            str(envelope.requirement_revision_id)
            if envelope.requirement_revision_id is not None
            else None
        ),
        requirement_revision_no=(
            int(envelope.requirement_revision_no)
            if envelope.requirement_revision_no is not None
            else None
        ),
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
