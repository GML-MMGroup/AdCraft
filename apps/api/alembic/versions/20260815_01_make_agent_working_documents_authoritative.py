"""Version authoritative Agent working documents and patch receipts.

Revision ID: 20260815_01
Revises: 20260812_03
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260815_01"
down_revision = "20260812_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_working_documents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "content_schema_version",
                sa.Integer(),
                nullable=False,
                server_default="2",
            )
        )
    with op.batch_alter_table("agent_working_document_patch_receipts") as batch_op:
        batch_op.add_column(
            sa.Column("before_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("after_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("result_digest", sa.Text(), nullable=False, server_default="")
        )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT receipt_id, result_json FROM agent_working_document_patch_receipts")
    ).mappings()
    for row in rows:
        result = json.loads(str(row["result_json"]))
        after_revision = int(result["revision"])
        connection.execute(
            sa.text(
                "UPDATE agent_working_document_patch_receipts "
                "SET before_revision=:before_revision, after_revision=:after_revision, "
                "result_digest=:result_digest WHERE receipt_id=:receipt_id"
            ),
            {
                "before_revision": max(0, after_revision - 1),
                "after_revision": after_revision,
                "result_digest": str(result["content_digest"]),
                "receipt_id": str(row["receipt_id"]),
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_working_document_patch_receipts") as batch_op:
        batch_op.drop_column("result_digest")
        batch_op.drop_column("after_revision")
        batch_op.drop_column("before_revision")
    with op.batch_alter_table("agent_working_documents") as batch_op:
        batch_op.drop_column("content_schema_version")
