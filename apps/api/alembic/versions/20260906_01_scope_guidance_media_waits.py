"""Allow media checkpoint waits alongside one authoring wait.

Revision ID: 20260906_01
Revises: 20260903_06
"""

from alembic import op
import sqlalchemy as sa

revision = "20260906_01"
down_revision = "20260903_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_guidance_awaiting") as batch:
        batch.drop_constraint("uq_agent_canvas_guidance_awaiting_workflow", type_="unique")
    op.create_index(
        "uq_agent_canvas_guidance_awaiting_authoring",
        "agent_canvas_guidance_awaiting",
        ["workflow_id"],
        unique=True,
        sqlite_where=sa.text("kind NOT IN ('manual_node_run','media_review')"),
    )


def downgrade() -> None:
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT workflow_id FROM agent_canvas_guidance_awaiting "
                "GROUP BY workflow_id HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicates is not None:
        raise RuntimeError("Scoped waits must settle before downgrading Guidance authority.")
    op.drop_index(
        "uq_agent_canvas_guidance_awaiting_authoring",
        table_name="agent_canvas_guidance_awaiting",
    )
    with op.batch_alter_table("agent_canvas_guidance_awaiting") as batch:
        batch.create_unique_constraint(
            "uq_agent_canvas_guidance_awaiting_workflow", ["workflow_id"]
        )
