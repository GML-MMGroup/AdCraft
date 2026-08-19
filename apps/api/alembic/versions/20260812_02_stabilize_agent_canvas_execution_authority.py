"""Stabilize Agent Canvas execution and result authority.

Revision ID: 20260812_02
Revises: 20260812_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_02"
down_revision = "20260812_01"
branch_labels = None
depends_on = None

_ACTIVE = ("queued", "running", "waiting")
_TERMINAL_MEMBERS = ("succeeded", "failed", "cancelled")


def upgrade() -> None:
    connection = op.get_bind()
    _reconcile_or_reject_duplicate_active(connection)
    if not _index_exists(connection, "uq_agent_canvas_executions_active_workflow"):
        op.create_index(
            "uq_agent_canvas_executions_active_workflow",
            "agent_canvas_executions",
            ["workflow_id"],
            unique=True,
            sqlite_where=sa.text("status IN ('queued','running','waiting')"),
        )
    op.create_table(
        "agent_canvas_execution_admissions",
        sa.Column("admission_id", sa.Text(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("request_digest", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_canvas_executions.execution_id"]),
    )
    op.create_table(
        "agent_canvas_provider_submission_intents",
        sa.Column("intent_id", sa.Text(), primary_key=True),
        sa.Column("logical_operation_key", sa.Text(), nullable=False),
        sa.Column("request_digest", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("member_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("supports_idempotency_token", sa.Boolean(), nullable=False),
        sa.Column("supports_remote_task_lookup", sa.Boolean(), nullable=False),
        sa.Column("provider_idempotency_token", sa.Text()),
        sa.Column("remote_task_id", sa.Text()),
        sa.Column("provider_task_id", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "state IN ('prepared','submitted','outcome_unknown','completed')",
            name="ck_agent_canvas_provider_submission_intents_state",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_canvas_executions.execution_id"]),
        sa.ForeignKeyConstraint(["member_id"], ["agent_canvas_execution_members.member_id"]),
        sa.ForeignKeyConstraint(["node_id"], ["agent_canvas_nodes.node_id"]),
        sa.UniqueConstraint(
            "logical_operation_key",
            name="uq_agent_canvas_provider_submission_intents_operation",
        ),
    )
    op.create_index(
        "ix_agent_canvas_provider_submission_intents_recovery",
        "agent_canvas_provider_submission_intents",
        ["state", "updated_at"],
    )
    with op.batch_alter_table("agent_canvas_provider_tasks") as batch:
        batch.add_column(sa.Column("submission_intent_id", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_agent_canvas_provider_tasks_submission_intent",
            "agent_canvas_provider_submission_intents",
            ["submission_intent_id"],
            ["intent_id"],
        )
    op.create_table(
        "agent_canvas_execution_result_commits",
        sa.Column("commit_id", sa.Text(), primary_key=True),
        sa.Column("logical_result_key", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("member_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text()),
        sa.Column("version_id", sa.Text()),
        sa.Column("event_cursor", sa.Integer(), nullable=False),
        sa.Column("receipt_json", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('succeeded','failed','cancelled')",
            name="ck_agent_canvas_execution_result_commits_outcome",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_canvas_executions.execution_id"]),
        sa.ForeignKeyConstraint(["member_id"], ["agent_canvas_execution_members.member_id"]),
        sa.ForeignKeyConstraint(["node_id"], ["agent_canvas_nodes.node_id"]),
        sa.UniqueConstraint(
            "logical_result_key",
            name="uq_agent_canvas_execution_result_commits_result_key",
        ),
        sa.UniqueConstraint(
            "execution_id",
            "member_id",
            name="uq_agent_canvas_execution_result_commits_member",
        ),
    )
    op.create_table(
        "agent_canvas_post_ready_effects",
        sa.Column("effect_id", sa.Text(), primary_key=True),
        sa.Column("effect_type", sa.Text(), nullable=False),
        sa.Column("source_commit_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("lease_owner_id", sa.Text()),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.Text()),
        sa.Column("error_json", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "effect_type IN "
            "('persist_script_document','persist_text_document','advance_storyboard_progression')",
            name="ck_agent_canvas_post_ready_effects_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_agent_canvas_post_ready_effects_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_commit_id"], ["agent_canvas_execution_result_commits.commit_id"]
        ),
    )
    op.create_index(
        "ix_agent_canvas_post_ready_effects_due",
        "agent_canvas_post_ready_effects",
        ["status", "lease_expires_at", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_canvas_post_ready_effects_due",
        table_name="agent_canvas_post_ready_effects",
    )
    op.drop_table("agent_canvas_post_ready_effects")
    op.drop_table("agent_canvas_execution_result_commits")
    with op.batch_alter_table("agent_canvas_provider_tasks") as batch:
        batch.drop_constraint(
            "fk_agent_canvas_provider_tasks_submission_intent", type_="foreignkey"
        )
        batch.drop_column("submission_intent_id")
    op.drop_index(
        "ix_agent_canvas_provider_submission_intents_recovery",
        table_name="agent_canvas_provider_submission_intents",
    )
    op.drop_table("agent_canvas_provider_submission_intents")
    op.drop_table("agent_canvas_execution_admissions")
    if _index_exists(op.get_bind(), "uq_agent_canvas_executions_active_workflow"):
        op.drop_index(
            "uq_agent_canvas_executions_active_workflow",
            table_name="agent_canvas_executions",
        )


def _index_exists(connection: sa.Connection, name: str) -> bool:
    return bool(
        connection.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:name"),
            {"name": name},
        ).scalar_one_or_none()
    )


def _reconcile_or_reject_duplicate_active(connection: sa.Connection) -> None:
    workflows = connection.execute(
        sa.text(
            "SELECT workflow_id FROM agent_canvas_executions "
            "WHERE status IN ('queued','running','waiting') "
            "GROUP BY workflow_id HAVING COUNT(*) > 1"
        )
    ).scalars()
    for workflow_id in workflows:
        rows = connection.execute(
            sa.text(
                "SELECT e.execution_id, "
                "SUM(CASE WHEN m.state NOT IN ('succeeded','failed','cancelled') THEN 1 ELSE 0 END) "
                "AS open_members, "
                "SUM(CASE WHEN p.status IN ('submitted','waiting','recovering') THEN 1 ELSE 0 END) "
                "AS open_tasks "
                "FROM agent_canvas_executions e "
                "LEFT JOIN agent_canvas_execution_members m ON m.execution_id=e.execution_id "
                "LEFT JOIN agent_canvas_provider_tasks p ON p.execution_id=e.execution_id "
                "WHERE e.workflow_id=:workflow_id "
                "AND e.status IN ('queued','running','waiting') GROUP BY e.execution_id"
            ),
            {"workflow_id": workflow_id},
        ).mappings()
        unresolved = []
        for row in rows:
            if int(row["open_members"] or 0) == 0 and int(row["open_tasks"] or 0) == 0:
                connection.execute(
                    sa.text(
                        "UPDATE agent_canvas_executions SET status='completed' "
                        "WHERE execution_id=:execution_id"
                    ),
                    {"execution_id": row["execution_id"]},
                )
            else:
                unresolved.append(str(row["execution_id"]))
        if len(unresolved) > 1:
            raise RuntimeError(
                "active_execution_migration_conflict: " + ",".join(sorted(unresolved))
            )
