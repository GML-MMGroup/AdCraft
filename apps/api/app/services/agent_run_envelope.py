"""Deterministic compatibility fields for private Pi Agent requests."""

from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel

from app.services.v2_agent_runtime_manifest import V2AgentRuntimeManifestService


def agent_run_envelope_fields(context: BaseModel) -> dict[str, str]:
    """Return the checked-in contract identity and a bounded context identity."""

    context_digest = sha256(context.model_dump_json().encode("utf-8")).hexdigest()
    return {
        "contract_digest": V2AgentRuntimeManifestService().expected().contract_digest,
        "context_snapshot_id": f"context_{context_digest}",
    }
