"""Add bounded presentation delivery storage."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260827_01"
down_revision = "20260826_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "presentation_streams",
        sa.Column("stream_id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("stream_kind", sa.Text(), nullable=False),
        sa.Column("generation_id", sa.Text(), nullable=False),
        sa.Column("turn_id", sa.Text()),
        sa.Column("node_id", sa.Text()),
        sa.Column("node_revision", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("last_sequence_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("authoritative_id", sa.Text()),
        sa.Column("content_digest", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("timing_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("terminal_at", sa.Text()),
        sa.ForeignKeyConstraint(["workflow_id"], ["agent_canvas_workflows.workflow_id"]),
        sa.CheckConstraint(
            "stream_kind IN ('assistant', 'node_prompt')",
            name="ck_presentation_streams_kind",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'completed', 'failed', 'superseded')",
            name="ck_presentation_streams_status",
        ),
        sa.CheckConstraint("last_sequence_no >= 0", name="ck_presentation_streams_sequence"),
        sa.UniqueConstraint("idempotency_key", name="uq_presentation_streams_idempotency"),
    )
    op.create_index(
        "ix_presentation_streams_workflow", "presentation_streams", ["workflow_id", "updated_at"]
    )
    op.create_table(
        "presentation_stream_chunks",
        sa.Column("chunk_id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Text(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column("event_json", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["stream_id"], ["presentation_streams.stream_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("stream_id", "sequence_no", name="uq_presentation_chunks_sequence"),
        sa.UniqueConstraint("stream_id", "event_key", name="uq_presentation_chunks_event_key"),
    )
    op.create_index(
        "ix_presentation_chunks_stream_sequence",
        "presentation_stream_chunks",
        ["stream_id", "sequence_no"],
    )


def downgrade() -> None:
    op.drop_index("ix_presentation_chunks_stream_sequence", table_name="presentation_stream_chunks")
    op.drop_table("presentation_stream_chunks")
    op.drop_index("ix_presentation_streams_workflow", table_name="presentation_streams")
    op.drop_table("presentation_streams")
