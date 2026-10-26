"""Deterministic separation of creative inputs from Node execution settings."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Mapping

from pydantic import JsonValue

from app.schemas.agent_canvas import CanvasNodeV2


# Unknown parameters remain creative. Duration, aspect ratio, audio policy,
# representation and role discriminators must never acquire an exemption here.
_EXECUTION_ONLY_PARAMETERS = frozenset({"seed", "resolution"})


def creative_parameters(parameters: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Keep every parameter except the explicitly classified execution controls."""

    return {
        key: value for key, value in parameters.items() if key not in _EXECUTION_ONLY_PARAMETERS
    }


def creative_node_inputs(node: CanvasNodeV2) -> dict[str, object]:
    """Project content authority independently of display, media and model revisions."""

    return {
        "policy": "node-creative-inputs-v1",
        "node_type": node.node_type,
        "creative_role": node.creative_role,
        "role_contract_version": node.role_contract_version,
        "execution_mode": node.execution_mode,
        "summary_prompt": node.summary_prompt,
        "generation_prompt": node.generation_prompt,
        "structured_content": node.structured_content,
        "parameters": creative_parameters(node.parameters),
    }


def creative_node_inputs_changed(current: CanvasNodeV2, requested: CanvasNodeV2) -> bool:
    return creative_node_inputs(current) != creative_node_inputs(requested)


def creative_node_input_digest(node: CanvasNodeV2) -> str:
    payload = json.dumps(
        creative_node_inputs(node), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return sha256(payload.encode("utf-8")).hexdigest()
