"""Add typed Agent working documents.

Revision ID: 20260806_05
Revises: 20260806_04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260806_05"
down_revision = "20260806_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "metadata_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
    op.create_table(
        "agent_working_documents",
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("guidance_session_id", sa.Text(), nullable=False),
        sa.Column("document_kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_by_agent_run_id", sa.Text(), nullable=False),
        sa.Column("updated_by_agent_run_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "document_kind IN ('anchor_registry', 'storyboard_production_plan')",
            name="ck_agent_working_documents_kind",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_agent_working_documents_revision",
        ),
        sa.ForeignKeyConstraint(
            ["guidance_session_id"],
            ["agent_canvas_guidance_sessions.session_id"],
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["agent_canvas_workflows.workflow_id"],
        ),
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint(
            "workflow_id",
            "guidance_session_id",
            "document_kind",
            name="uq_agent_working_documents_scope_kind",
        ),
    )
    op.create_index(
        "ix_agent_working_documents_workflow_updated",
        "agent_working_documents",
        ["workflow_id", "updated_at", "document_id"],
        unique=False,
    )
    op.create_table(
        "agent_working_document_patch_receipts",
        sa.Column("receipt_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("request_digest", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["agent_working_documents.document_id"],
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
        sa.UniqueConstraint(
            "document_id",
            "idempotency_key",
            name="uq_agent_working_document_patch_receipt_key",
        ),
    )
    op.create_index(
        "ix_agent_working_document_patch_receipts_document_created",
        "agent_working_document_patch_receipts",
        ["document_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_working_document_patch_receipts_document_created",
        table_name="agent_working_document_patch_receipts",
    )
    op.drop_table("agent_working_document_patch_receipts")
    op.drop_index(
        "ix_agent_working_documents_workflow_updated",
        table_name="agent_working_documents",
    )
    op.drop_table("agent_working_documents")
    with op.batch_alter_table("agent_canvas_nodes") as batch_op:
        batch_op.drop_column("metadata_json")
