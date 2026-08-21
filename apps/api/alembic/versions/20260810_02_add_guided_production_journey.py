"""Add persisted guided production journey state.

Revision ID: 20260810_02
Revises: 20260810_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_02"
down_revision = "20260810_01"
branch_labels = None
depends_on = None


_INITIAL_JOURNEY = (
    '{"policy_version":"fixed_ad_production_v1","stage":"intake",'
    '"stage_status":"ready","stage_revision":1,"foundation_queue":[],'
    '"foundation_cursor":null,"active_action":null,"suspended_action":null,'
    '"transition_evidence":[]}'
)


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_guidance_sessions") as batch:
        batch.add_column(
            sa.Column(
                "journey_state_json",
                sa.Text(),
                nullable=False,
                server_default=_INITIAL_JOURNEY,
            )
        )
    op.get_bind().exec_driver_sql(
        "UPDATE agent_canvas_guidance_sessions SET "
        "current_checkpoint_json = NULL, current_topic_id = NULL, "
        "active_proposal_id = NULL, journey_state_json = ?",
        (_INITIAL_JOURNEY,),
    )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_guidance_sessions") as batch:
        batch.drop_column("journey_state_json")
