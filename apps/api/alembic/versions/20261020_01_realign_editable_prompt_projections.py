"""Realign editable prompt projections left behind by prompt-preserving bumps.

Before 2026-10-20, ready-prompt reference refreshes bumped the Node revision
without moving the editable prompt projection; combined with a derived Video
parameter write this failed provider compilation with prompt_revision_conflict.
Projections in neither valid resting shape, whose text and digest still equal
the Node prompt, move to the Node revision together with their review marker.
"""

from __future__ import annotations

from hashlib import sha256
import json

from alembic import op
import sqlalchemy as sa


revision = "20261020_01"
down_revision = "20261014_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT workflow_id, node_id, revision, generation_prompt, metadata_json "
            "FROM agent_canvas_nodes "
            "WHERE json_extract(metadata_json, '$.editable_prompt_projection.revision') "
            "IS NOT NULL"
        )
    ).mappings()
    for row in list(rows):
        metadata = json.loads(row["metadata_json"] or "{}")
        projection = metadata.get("editable_prompt_projection")
        prompt = row["generation_prompt"]
        if not isinstance(projection, dict) or not isinstance(prompt, str):
            continue
        node_revision = int(row["revision"])
        projection_revision = projection.get("revision")
        review_revision = metadata.get("guided_review_node_revision")
        if projection_revision == node_revision:
            continue
        if projection_revision == node_revision - 1 and review_revision in {
            node_revision,
            projection_revision,
        }:
            # Valid resting shapes: guided review, or the deliberate one-revision
            # lag after a derived Video parameter write.
            continue
        expected_digest = f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
        if projection.get("text") != prompt or projection.get("prompt_digest") != expected_digest:
            continue
        projection["revision"] = node_revision
        if review_revision == projection_revision:
            metadata["guided_review_node_revision"] = node_revision
        connection.execute(
            sa.text(
                "UPDATE agent_canvas_nodes SET metadata_json = :metadata "
                "WHERE workflow_id = :workflow_id AND node_id = :node_id "
                "AND revision = :revision"
            ),
            {
                "metadata": json.dumps(
                    metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
                "workflow_id": row["workflow_id"],
                "node_id": row["node_id"],
                "revision": node_revision,
            },
        )


def downgrade() -> None:
    """The realignment is a data repair; there is nothing to undo."""
