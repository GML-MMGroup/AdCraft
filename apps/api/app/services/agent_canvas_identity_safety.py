"""Default Agent-designed characters to fictional without blocking media on identity.

Identity never blocks generation, including uploaded photos of real people.
Seedance's provider-side filter is the only identity gate.
"""

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
    """Default missing required decisions to fictional; never reject a likeness.

    Agent-designed characters are fictional by default. Uploaded real-person photos
    are also allowed; only Seedance's provider-side filter gates identity. Explicit
    decisions still require valid structure and current revision provenance.
    """

    synthesized_default = decision is None and required
    if decision is None:
        if not required:
            return None
        decision = IdentitySafetyDecisionV1(
            classification="fictional",
            source="platform_default",
            normalized_revision="platform-default",
        )
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
    if (
        not synthesized_default
        and expected_normalized_revision is not None
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
