"""Resolve normalized identity safety before live-action media admission."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from pydantic import ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_identity_safety import IdentitySafetyDecisionV1


_POLICY_VERSION = "identity-safety-v1"


@dataclass(frozen=True, slots=True)
class IdentitySafetyResolutionV1:
    decision: IdentitySafetyDecisionV1
    policy_version: str
    digest: str


def resolve_identity_safety_decision(
    decision: IdentitySafetyDecisionV1 | object | None,
    *,
    required: bool = False,
    expected_normalized_revision: str | None = None,
) -> IdentitySafetyResolutionV1 | None:
    """Validate one normalized decision without inspecting any creative text."""

    if decision is None:
        if required:
            raise V2PersistenceError(
                "identity_safety_decision_required",
                "A normalized identity safety decision is required before live-action admission.",
                stage="identity_safety",
            )
        return None
    try:
        normalized = (
            decision
            if isinstance(decision, IdentitySafetyDecisionV1)
            else IdentitySafetyDecisionV1.model_validate(decision)
        )
    except ValidationError as error:
        raise V2PersistenceError(
            "identity_safety_decision_invalid",
            "The normalized identity safety decision is invalid.",
            stage="identity_safety",
        ) from error
    if normalized.classification == "identifiable_person_likeness":
        raise V2PersistenceError(
            "identifiable_person_likeness_unsupported",
            "Specific identifiable-person likeness is not supported.",
            stage="identity_safety",
        )
    if (
        expected_normalized_revision is not None
        and normalized.normalized_revision != expected_normalized_revision
    ):
        raise V2PersistenceError(
            "identity_safety_decision_stale",
            "The identity safety decision does not match the current normalized revision.",
            stage="identity_safety",
        )
    payload = {
        "policy_version": _POLICY_VERSION,
        "decision": normalized.model_dump(mode="json"),
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return IdentitySafetyResolutionV1(
        decision=normalized,
        policy_version=_POLICY_VERSION,
        digest=f"sha256:{digest}",
    )
