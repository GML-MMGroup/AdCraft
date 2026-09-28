"""Exact operation evidence gates for operator-configured native Pi models."""

from __future__ import annotations

from hashlib import sha256
import json

from app.persistence.provider_model_repository import (
    ProviderModelConformanceRunRecord,
    ProviderModelRecord,
)
from app.services.agent_operation_policy import AgentOperationPolicyRegistryV2
from app.services.v2_agent_runtime_manifest import V2AgentRuntimeManifestService
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


NATIVE_AGENT_ADAPTER = "pi-openai-compatible-v1"
REQUIRED_CHECKS = (
    "structured_output",
    "tool_calls",
    "reasoning_controls",
    "streaming",
    "timeout_policy",
    "transport",
)


def requires_operation_evidence(model: ProviderModelRecord) -> bool:
    return model.source == "configured" and model.capability == "text"


def operation_policy_digest(operation: str) -> str:
    definition = VideoAgentOperationRegistry().resolve(operation)
    policy = AgentOperationPolicyRegistryV2().resolve(
        agent_name="video_agent", operation=operation, contract_id=definition.result_contract_name
    )
    encoded = json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode()).hexdigest()}"


def configured_operation_status(
    model: ProviderModelRecord,
    operation: str,
    evidence: ProviderModelConformanceRunRecord | None,
) -> str:
    """Check current identity and review without treating availability as evidence."""

    registration = model.capability_metadata.get("version_registration", {})
    if registration.get("state") == "rejected":
        return "revoked"
    if registration.get("state") != "approved" or evidence is None:
        return "unverified"
    if (
        evidence.model_ref != model.model_ref
        or evidence.provider_id != model.provider_id
        or evidence.provider_model_id != model.provider_model_id
        or evidence.operation != operation
        or evidence.adapter_id != NATIVE_AGENT_ADAPTER
        or evidence.adapter_revision != NATIVE_AGENT_ADAPTER
        or evidence.transport_kind != "pi_native_openai_compatible"
        or evidence.capability_revision != model.capability_metadata.get("capability_revision")
        or evidence.contract_digest != V2AgentRuntimeManifestService().expected().contract_digest
        or evidence.safe_summary.get("catalog_revision") != model.catalog_revision
        or evidence.safe_summary.get("operation_policy_digest")
        != operation_policy_digest(operation)
        or evidence.completed_at is None
    ):
        return "unverified"
    if evidence.status == "revoked":
        return "revoked"
    checks = evidence.safe_summary.get("checks")
    if (
        evidence.status not in {"compatible", "certified"}
        or not isinstance(checks, dict)
        or any(checks.get(key) is not True for key in REQUIRED_CHECKS)
    ):
        return "unverified"
    return evidence.status


def require_configured_operation(
    model: ProviderModelRecord,
    operation: str,
    evidence: ProviderModelConformanceRunRecord | None,
) -> None:
    if not requires_operation_evidence(model):
        return
    status = configured_operation_status(model, operation, evidence)
    if status not in {"compatible", "certified"}:
        raise ValueError(
            "model_conformance_revoked" if status == "revoked" else "model_conformance_required"
        )
