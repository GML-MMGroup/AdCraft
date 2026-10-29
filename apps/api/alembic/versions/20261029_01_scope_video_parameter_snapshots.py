"""Keep immutable parameter snapshots for each preparation intent."""

from alembic import op
import sqlalchemy as sa

revision = "20261029_01"
down_revision = "20261028_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_video_parameter_compilation_snapshots") as batch:
        batch.add_column(
            sa.Column("preparation_scope", sa.Text(), nullable=False, server_default="legacy")
        )
        batch.drop_constraint("uq_agent_canvas_video_parameter_snapshot_member", type_="unique")
        batch.create_unique_constraint(
            "uq_agent_canvas_video_parameter_snapshot_scope", ["member_id", "preparation_scope"]
        )


def downgrade() -> None:
    # Multiple immutable snapshots cannot be collapsed without losing history.
    raise RuntimeError("Restore the pre-upgrade backup to downgrade preparation-scoped snapshots.")
