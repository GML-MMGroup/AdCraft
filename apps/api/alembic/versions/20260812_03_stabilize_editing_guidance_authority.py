"""Stabilize Agent Canvas Editing and Guidance authority.

Revision ID: 20260812_03
Revises: 20260812_02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_03"
down_revision = "20260812_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    _reject_ambiguous_active_exports(connection)
    _reconcile_or_reject_active_continuations(connection)
    with op.batch_alter_table("agent_canvas_editing_exports") as batch:
        batch.add_column(sa.Column("lease_owner_id", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("lease_heartbeat_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.Text(), nullable=True))
    op.create_table(
        "agent_canvas_editing_export_commits",
        sa.Column("commit_id", sa.Text(), primary_key=True),
        sa.Column("export_id", sa.Text(), nullable=False),
        sa.Column("logical_commit_key", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text()),
        sa.Column("version_id", sa.Text()),
        sa.Column("receipt_json", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('completed','failed','cancelled')",
            name="ck_agent_canvas_editing_export_commits_outcome",
        ),
        sa.ForeignKeyConstraint(["export_id"], ["agent_canvas_editing_exports.export_id"]),
        sa.UniqueConstraint(
            "logical_commit_key",
            name="uq_agent_canvas_editing_export_commits_logical_key",
        ),
        sa.UniqueConstraint(
            "export_id",
            name="uq_agent_canvas_editing_export_commits_export",
        ),
    )
    op.create_index(
        "uq_agent_canvas_editing_export_active_node",
        "agent_canvas_editing_exports",
        ["workflow_id", "node_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued','exporting')"),
    )
    op.create_index(
        "uq_agent_canvas_continuation_active_workflow",
        "agent_canvas_continuation_outbox",
        ["workflow_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued','leased','retry_wait')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_canvas_continuation_active_workflow",
        table_name="agent_canvas_continuation_outbox",
    )
    op.drop_index(
        "uq_agent_canvas_editing_export_active_node",
        table_name="agent_canvas_editing_exports",
    )
    op.drop_table("agent_canvas_editing_export_commits")
    with op.batch_alter_table("agent_canvas_editing_exports") as batch:
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_heartbeat_at")
        batch.drop_column("lease_generation")
        batch.drop_column("lease_owner_id")


def _reject_ambiguous_active_exports(connection: sa.Connection) -> None:
    conflicts = connection.execute(
        sa.text(
            "SELECT workflow_id, node_id FROM agent_canvas_editing_exports "
            "WHERE status IN ('queued','exporting') "
            "GROUP BY workflow_id, node_id HAVING COUNT(*) > 1"
        )
    ).mappings()
    identities = sorted(f"{row['workflow_id']}:{row['node_id']}" for row in conflicts)
    if identities:
        raise RuntimeError("active_editing_export_migration_conflict: " + ",".join(identities))


def _reconcile_or_reject_active_continuations(connection: sa.Connection) -> None:
    workflows = connection.execute(
        sa.text(
            "SELECT workflow_id FROM agent_canvas_continuation_outbox "
            "WHERE status IN ('queued','leased','retry_wait') "
            "GROUP BY workflow_id HAVING COUNT(*) > 1"
        )
    ).scalars()
    ambiguous: list[str] = []
    for workflow_id in workflows:
        rows = connection.execute(
            sa.text(
                "SELECT c.continuation_id, c.continuation_turn_id, t.status AS turn_status "
                "FROM agent_canvas_continuation_outbox c "
                "LEFT JOIN agent_canvas_chat_turns t ON t.turn_id=c.continuation_turn_id "
                "WHERE c.workflow_id=:workflow_id "
                "AND c.status IN ('queued','leased','retry_wait')"
            ),
            {"workflow_id": workflow_id},
        ).mappings()
        unresolved: list[str] = []
        for row in rows:
            turn_status = str(row["turn_status"] or "")
            if turn_status in {"completed", "failed", "cancelled"}:
                terminal = "completed" if turn_status == "completed" else "failed"
                connection.execute(
                    sa.text(
                        "UPDATE agent_canvas_continuation_outbox SET status=:status "
                        "WHERE continuation_id=:continuation_id"
                    ),
                    {
                        "status": terminal,
                        "continuation_id": row["continuation_id"],
                    },
                )
            else:
                unresolved.append(str(row["continuation_id"]))
        if len(unresolved) > 1:
            ambiguous.extend(unresolved)
    if ambiguous:
        raise RuntimeError("active_continuation_migration_conflict: " + ",".join(sorted(ambiguous)))
