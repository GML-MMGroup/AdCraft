"""Repair provable Agent Canvas Character pair metadata.

Revision ID: 20260812_01
Revises: 20260811_02
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260812_01"
down_revision = "20260811_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    candidates = connection.execute(
        sa.text(
            "SELECT b.binding_id, b.workflow_id, b.source_node_id, b.target_node_id, "
            "b.metadata_json AS binding_metadata, "
            "s.node_type AS source_type, s.creative_role AS source_role, "
            "s.structured_content_json AS source_content, s.parameters_json AS source_parameters, "
            "s.metadata_json AS source_metadata, "
            "t.node_type AS target_type, t.creative_role AS target_role, "
            "t.structured_content_json AS target_content, t.parameters_json AS target_parameters, "
            "t.metadata_json AS target_metadata "
            "FROM agent_canvas_bindings b "
            "JOIN agent_canvas_nodes s ON s.node_id=b.source_node_id "
            "JOIN agent_canvas_nodes t ON t.node_id=b.target_node_id "
            "WHERE b.source_kind='node_output' AND b.input_role='image_reference' "
            "AND b.required=1 AND b.enabled=1"
        )
    ).mappings()
    repaired = 0
    ambiguous = 0
    for row in candidates:
        evidence = _repair_evidence(connection, row)
        if evidence is None:
            ambiguous += 1
            continue
        materialization_id, pair_id = evidence
        del materialization_id
        source_metadata = _json_object(row["source_metadata"])
        target_metadata = _json_object(row["target_metadata"])
        binding_metadata = _json_object(row["binding_metadata"])
        source_metadata["character_pair_id"] = pair_id
        target_metadata["character_pair_id"] = pair_id
        binding_metadata.update(
            {
                "character_pair_id": pair_id,
                "reference_purpose": "identity_master",
                "semantic_reference_role": "subject_reference",
            }
        )
        connection.execute(
            sa.text("UPDATE agent_canvas_nodes SET metadata_json=:metadata WHERE node_id=:node_id"),
            [
                {
                    "metadata": _json_dump(source_metadata),
                    "node_id": row["source_node_id"],
                },
                {
                    "metadata": _json_dump(target_metadata),
                    "node_id": row["target_node_id"],
                },
            ],
        )
        connection.execute(
            sa.text(
                "UPDATE agent_canvas_bindings SET metadata_json=:metadata "
                "WHERE binding_id=:binding_id"
            ),
            {
                "metadata": _json_dump(binding_metadata),
                "binding_id": row["binding_id"],
            },
        )
        repaired += 1
    print(
        "Character pair metadata migration completed: "
        f"repaired={repaired}, ambiguous_or_unrelated={ambiguous}."
    )


def downgrade() -> None:
    """Keep repaired metadata; rollback requires the pre-migration database backup."""


def _repair_evidence(
    connection: Any,
    row: sa.RowMapping,
) -> tuple[str, str] | None:
    if (
        row["source_type"] != "image"
        or row["target_type"] != "image"
        or row["source_role"] != "character"
        or row["target_role"] != "character"
    ):
        return None
    source_content = _json_object(row["source_content"])
    target_content = _json_object(row["target_content"])
    if (
        source_content.get("character_asset_kind") != "identity_master"
        or target_content.get("character_asset_kind") != "turnaround"
    ):
        return None
    source_parameters = _json_object(row["source_parameters"])
    target_parameters = _json_object(row["target_parameters"])
    proposal_id = source_parameters.get("source_proposal_id")
    option_id = source_parameters.get("source_option_id")
    if (
        not isinstance(proposal_id, str)
        or not isinstance(option_id, str)
        or target_parameters.get("source_proposal_id") != proposal_id
        or target_parameters.get("source_option_id") != option_id
    ):
        return None
    matching_commits: list[str] = []
    commits = connection.execute(
        sa.text(
            "SELECT materialization_id, outcome_json "
            "FROM agent_canvas_materialization_commits "
            "WHERE workflow_id=:workflow_id AND proposal_id=:proposal_id"
        ),
        {"workflow_id": row["workflow_id"], "proposal_id": proposal_id},
    ).mappings()
    for commit in commits:
        outcome = _json_object(commit["outcome_json"])
        if (
            row["source_node_id"] in _string_set(outcome.get("node_ids"))
            and row["target_node_id"] in _string_set(outcome.get("node_ids"))
            and row["binding_id"] in _string_set(outcome.get("binding_ids"))
        ):
            matching_commits.append(str(commit["materialization_id"]))
    if len(matching_commits) != 1:
        return None
    competing = connection.execute(
        sa.text(
            "SELECT s.structured_content_json "
            "FROM agent_canvas_bindings b "
            "JOIN agent_canvas_nodes s ON s.node_id=b.source_node_id "
            "WHERE b.target_node_id=:target_node_id AND b.binding_id<>:binding_id "
            "AND b.source_kind='node_output' AND b.input_role='image_reference' "
            "AND b.required=1 AND b.enabled=1"
        ),
        {"target_node_id": row["target_node_id"], "binding_id": row["binding_id"]},
    ).scalars()
    if any(
        _json_object(content).get("character_asset_kind") == "identity_master"
        for content in competing
    ):
        return None
    materialization_id = matching_commits[0]
    pair_id = f"pair_{sha256(materialization_id.encode('utf-8')).hexdigest()[:32]}"
    return materialization_id, pair_id


def _json_object(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _string_set(value: object) -> set[str]:
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def _json_dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
