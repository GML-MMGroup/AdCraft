"""Re-key completed prompt dispatches whose identity a reference refresh rewrote.

Between 2026-10-19 and 2026-10-21, refreshing a ready prompt's references
overwrote the completed dispatch's binding digest and source snapshot without
re-deriving its digest-complete logical key and dispatch ID. Every later read
of that workflow's dispatches then failed (prompt_preparation_dispatch_corrupt),
which blocked Agent turns. The original inputs were not retained, so the key and
ID are re-derived from the stored fields; events keep the historical ID.
"""

from __future__ import annotations

from hashlib import sha256
import json

from alembic import op
import sqlalchemy as sa


revision = "20261021_01"
down_revision = "20261020_01"
branch_labels = None
depends_on = None


def _logical_key(row: sa.RowMapping) -> str:
    # Frozen copy of prompt_preparation_dispatch_logical_key (2026-10-21).
    payload = {
        "workflow_id": row["workflow_id"],
        "node_id": row["node_id"],
        "node_revision": int(row["node_revision"]),
        "operation_id": row["operation_id"],
        "role_variant": row["role_variant"],
        "occurrence_id": row["occurrence_id"],
        "character_phase": row["character_phase"],
        "context_snapshot_id": row["context_snapshot_id"],
        "context_digest": row["context_digest"],
        "binding_digest": row["binding_digest"],
        "recipe_digest": row["recipe_digest"],
        "style_projection_digest": row["style_projection_digest"],
        "brief_digest": row["brief_digest"],
        "requirement_revision_id": row["requirement_revision_id"],
        "requirement_revision_no": (
            int(row["requirement_revision_no"])
            if row["requirement_revision_no"] is not None
            else None
        ),
        "document_revisions": dict(
            sorted(json.loads(str(row["document_revisions_json"] or "{}")).items())
        ),
        "source_snapshot": dict(json.loads(str(row["source_snapshot_json"] or "{}"))),
        "model_policy_revision": (
            int(row["model_policy_revision"]) if row["model_policy_revision"] is not None else None
        ),
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "ppd:" + sha256(encoded.encode("utf-8")).hexdigest()


def upgrade() -> None:
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.text(
                "SELECT * FROM agent_canvas_prompt_preparation_outbox WHERE status = 'completed'"
            )
        ).mappings()
    )
    for row in rows:
        logical_key = _logical_key(row)
        if logical_key == row["logical_key"]:
            continue
        dispatch_id = "ppd_" + sha256(logical_key.encode("utf-8")).hexdigest()[:40]
        connection.execute(
            sa.text(
                "UPDATE agent_canvas_prompt_preparation_outbox "
                "SET logical_key = :logical_key, dispatch_id = :dispatch_id "
                "WHERE dispatch_id = :old_dispatch_id"
            ),
            {
                "logical_key": logical_key,
                "dispatch_id": dispatch_id,
                "old_dispatch_id": row["dispatch_id"],
            },
        )
        connection.execute(
            sa.text(
                "UPDATE agent_canvas_prompt_preparation_outbox "
                "SET superseded_by_dispatch_id = :dispatch_id "
                "WHERE superseded_by_dispatch_id = :old_dispatch_id"
            ),
            {"dispatch_id": dispatch_id, "old_dispatch_id": row["dispatch_id"]},
        )


def downgrade() -> None:
    """The re-keying is a data repair; there is nothing to undo."""
