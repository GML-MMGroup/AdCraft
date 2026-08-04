"""Add durable Agent Canvas production integrity fields.

Revision ID: 20260803_27
Revises: 20260731_26
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260803_27"
down_revision = "20260731_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_production_recipes") as batch_op:
        batch_op.add_column(sa.Column("goal", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(
            sa.Column("deliverables_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("dependencies_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column(
                "recommended_next_topic_ids_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.add_column(
            sa.Column("completion_criteria_json", sa.Text(), nullable=False, server_default="{}")
        )

    with op.batch_alter_table("agent_canvas_concept_proposals") as batch_op:
        batch_op.add_column(sa.Column("target_node_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("target_node_revision", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("proposal_purpose", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("availability", sa.Text(), nullable=False, server_default="open")
        )
        batch_op.drop_constraint("uq_agent_canvas_proposal_publication_identity", type_="unique")
        batch_op.drop_column("publication_identity")
        batch_op.drop_constraint("ck_agent_canvas_concept_proposals_status", type_="check")
        batch_op.drop_column("selection_actor")
        batch_op.drop_column("selected_option_id")
        batch_op.drop_column("status")

    with op.batch_alter_table("agent_canvas_action_receipts") as batch_op:
        batch_op.add_column(sa.Column("proposal_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("proposal_option_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("proposal_generation_action", sa.Text(), nullable=True))

    with op.batch_alter_table("agent_canvas_guided_actions") as batch_op:
        batch_op.add_column(sa.Column("logical_key", sa.Text(), nullable=False, server_default=""))
    op.create_index(
        "uq_agent_canvas_guided_actions_workflow_logical_key",
        "agent_canvas_guided_actions",
        ["workflow_id", "logical_key"],
        unique=True,
        sqlite_where=sa.text("logical_key <> ''"),
    )

    with op.batch_alter_table("agent_canvas_expert_activities") as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.Text(), nullable=False, server_default=""))
        batch_op.drop_column("label")

    with op.batch_alter_table("agent_canvas_execution_members") as batch_op:
        batch_op.add_column(sa.Column("run_intent_snapshot_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("run_intent_snapshot_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("run_intent_snapshot_digest", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("resolved_input_manifest_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("resolved_input_manifest_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("resolved_input_manifest_digest", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("effective_parameters_json", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "omitted_optional_inputs_json", sa.Text(), nullable=False, server_default="[]"
            )
        )

    with op.batch_alter_table("asset_versions") as batch_op:
        batch_op.add_column(sa.Column("frame_rate", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("has_audio", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("asset_versions") as batch_op:
        batch_op.drop_column("has_audio")
        batch_op.drop_column("frame_rate")

    with op.batch_alter_table("agent_canvas_execution_members") as batch_op:
        batch_op.drop_column("omitted_optional_inputs_json")
        batch_op.drop_column("effective_parameters_json")
        batch_op.drop_column("resolved_input_manifest_digest")
        batch_op.drop_column("resolved_input_manifest_json")
        batch_op.drop_column("resolved_input_manifest_id")
        batch_op.drop_column("run_intent_snapshot_digest")
        batch_op.drop_column("run_intent_snapshot_json")
        batch_op.drop_column("run_intent_snapshot_id")

    with op.batch_alter_table("agent_canvas_concept_proposals") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.Text(), nullable=False, server_default="pending")
        )
        batch_op.add_column(sa.Column("selected_option_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("selection_actor", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("publication_identity", sa.Text(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_agent_canvas_proposal_publication_identity", ["publication_identity"]
        )
        batch_op.create_check_constraint(
            "ck_agent_canvas_concept_proposals_status",
            "status IN ('pending','selected','revised','skipped')",
        )
        batch_op.drop_column("availability")
        batch_op.drop_column("proposal_purpose")
        batch_op.drop_column("target_node_revision")
        batch_op.drop_column("target_node_id")

    with op.batch_alter_table("agent_canvas_action_receipts") as batch_op:
        batch_op.drop_column("proposal_generation_action")
        batch_op.drop_column("proposal_option_id")
        batch_op.drop_column("proposal_id")

    op.drop_index(
        "uq_agent_canvas_guided_actions_workflow_logical_key",
        table_name="agent_canvas_guided_actions",
    )
    with op.batch_alter_table("agent_canvas_guided_actions") as batch_op:
        batch_op.drop_column("logical_key")

    with op.batch_alter_table("agent_canvas_expert_activities") as batch_op:
        batch_op.add_column(sa.Column("label", sa.Text(), nullable=False, server_default=""))
        batch_op.drop_column("display_name")

    with op.batch_alter_table("agent_canvas_production_recipes") as batch_op:
        batch_op.drop_column("completion_criteria_json")
        batch_op.drop_column("recommended_next_topic_ids_json")
        batch_op.drop_column("dependencies_json")
        batch_op.drop_column("deliverables_json")
        batch_op.drop_column("goal")
