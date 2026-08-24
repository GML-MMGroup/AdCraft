"""Version persisted Proposal Cards for the public/private contract cutover."""

from alembic import op
import sqlalchemy as sa


revision = "20260823_01"
down_revision = "20260821_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.add_column(
            sa.Column(
                "proposal_card_schema_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_concept_proposals") as batch:
        batch.drop_column("proposal_card_schema_version")
