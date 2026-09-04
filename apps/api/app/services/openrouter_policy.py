"""Canonical frozen routing policy for exact OpenRouter model attempts."""

from __future__ import annotations

import hashlib
import json

from app.schemas.provider_models import OpenRouterRoutingPolicyV1


OPENROUTER_ROUTING_POLICY_ID = "openrouter-openai-only-v1"


def build_openrouter_routing_policy(
    *,
    model_ref: str,
    adapter_revision: str,
    capability_revision: str,
    operation_contract: str,
) -> OpenRouterRoutingPolicyV1:
    identity = {
        "adapter_revision": adapter_revision,
        "allow_fallbacks": False,
        "capability_revision": capability_revision,
        "model_ref": model_ref,
        "operation_contract": operation_contract,
        "provider_only": ["openai"],
        "require_parameters": True,
        "routing_policy_id": OPENROUTER_ROUTING_POLICY_ID,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return OpenRouterRoutingPolicyV1(
        routing_policy_id=OPENROUTER_ROUTING_POLICY_ID,
        routing_policy_digest=f"sha256:{digest}",
        require_parameters=True,
        allow_fallbacks=False,
        provider_only=("openai",),
    )
