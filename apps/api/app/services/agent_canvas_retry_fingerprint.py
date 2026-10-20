"""Stable authority fingerprints for Agent-journey retry validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from app.schemas.agent_canvas import (
    USER_AUTHORING_ORIGIN,
    USER_AUTHORING_ORIGIN_KEY,
    CanvasBindingV2,
    CanvasNodeV2,
)
from app.services.agent_canvas_node_ownership import agent_journey_nodes


def journey_fingerprint(
    nodes: Iterable[CanvasNodeV2], bindings: Iterable[CanvasBindingV2]
) -> tuple[dict[str, int], str]:
    """Return live Agent-node revisions and the Agent-to-Agent binding digest."""

    journey_nodes = agent_journey_nodes(nodes)
    node_revisions = {node.node_id: node.revision for node in journey_nodes}
    journey_ids = set(node_revisions)
    binding_records = []
    for binding in bindings:
        source_id = getattr(binding.source, "source_node_id", None)
        if source_id not in journey_ids or binding.target_node_id not in journey_ids:
            continue
        binding_records.append(
            _binding_record(
                binding_id=binding.binding_id,
                source=source_id,
                target=binding.target_node_id,
                enabled=binding.enabled,
                order=binding.order,
                input_role=binding.input_role,
                metadata=binding.metadata,
            )
        )
    return node_revisions, _digest(binding_records)


def journey_fingerprint_from_rows(
    node_rows: Iterable[Mapping[str, Any]], binding_rows: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, int], str]:
    """Row-oriented equivalent used while constructing snapshots in a transaction."""

    node_revisions: dict[str, int] = {}
    for row in node_rows:
        metadata = _json_object(row.get("metadata_json"))
        if isinstance(metadata.get("_deleted_at"), str):
            continue
        if metadata.get(USER_AUTHORING_ORIGIN_KEY) == USER_AUTHORING_ORIGIN:
            continue
        node_revisions[str(row["node_id"])] = int(row["revision"])
    binding_records = []
    for row in binding_rows:
        source = row.get("source_node_id")
        target = str(row["target_node_id"])
        if row.get("source_kind") != "node_output" or source not in node_revisions:
            continue
        if target not in node_revisions:
            continue
        binding_records.append(
            _binding_record(
                binding_id=str(row["binding_id"]),
                source=str(source),
                target=target,
                enabled=bool(row["enabled"]),
                order=int(row["order_index"]),
                input_role=str(row["input_role"]),
                metadata=_json_object(row.get("metadata_json")),
            )
        )
    return node_revisions, _digest(binding_records)


def _binding_record(
    *,
    binding_id: str,
    source: str,
    target: str,
    enabled: bool,
    order: int,
    input_role: str,
    metadata: Mapping[str, Any],
) -> dict[str, object]:
    return {
        "binding_id": binding_id,
        "source": source,
        "target": target,
        "enabled": enabled,
        "order": order,
        "input_role": input_role,
        "metadata_digest": hashlib.sha256(
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest(),
    }


def _digest(records: list[dict[str, object]]) -> str:
    records.sort(key=lambda record: (str(record["binding_id"]), str(record["source"])))
    return hashlib.sha256(
        json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}
