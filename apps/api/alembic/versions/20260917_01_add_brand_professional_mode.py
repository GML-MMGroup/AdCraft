"""Add brand professional mode persistence.

Revision ID: 20260917_01
Revises: 20260908_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_01"
down_revision = "20260908_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("mode", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_projects_mode",
            "mode IS NULL OR mode IN ('creation', 'brand')",
        )

    op.create_table(
        "brands",
        sa.Column("brand_id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "brand_facts",
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("slot_id", sa.Text(), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="fact"),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("brand_id", "stage", "slot_id", name="uq_brand_facts_slot"),
    )
    op.create_table(
        "brand_journeys",
        sa.Column("brand_id", sa.Text(), primary_key=True),
        sa.Column(
            "policy_version", sa.Text(), nullable=False, server_default="brand_professional_v1"
        ),
        sa.Column("stage", sa.Text(), nullable=False, server_default="brand-memory"),
        sa.Column("treatment_substep", sa.Text(), nullable=True),
        sa.Column("stage_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("stage_status", sa.Text(), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "brand_hypotheses",
        sa.Column("hypothesis_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("insight", sa.Text(), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=False),
        sa.Column("hypothesis_text", sa.Text(), nullable=False),
        sa.Column("product_role", sa.Text(), nullable=False),
        sa.Column("hook_mechanism", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "brand_adspec_items",
        sa.Column("item_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("item_text", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="open"),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("brand_id", "item_key", name="uq_brand_adspec_items_key"),
    )
    op.create_table(
        "brand_skill_stack",
        sa.Column("entry_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("skill_kind", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "brand_id", "skill_kind", "skill_id", name="uq_brand_skill_stack_entry"
        ),
    )
    op.create_table(
        "brand_treatment_steps",
        sa.Column("step_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("step_key", sa.Text(), nullable=False),
        sa.Column("selected_label", sa.Text(), nullable=False),
        sa.Column("detail_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("confirmed_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("brand_id", "step_key", name="uq_brand_treatment_steps_key"),
    )
    op.create_table(
        "brand_option_cards",
        sa.Column("card_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("stage_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("target_slot_id", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "brand_invocations",
        sa.Column("invocation_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("capability_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
    )
    op.create_table(
        "brand_decision_log",
        sa.Column("log_id", sa.Text(), primary_key=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "creative_skill_catalog",
        sa.Column("entry_id", sa.Text(), primary_key=True),
        sa.Column("skill_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("skill_kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("skill_id", "version", name="uq_creative_skill_catalog_version"),
    )


def downgrade() -> None:
    op.drop_table("creative_skill_catalog")
    op.drop_table("brand_decision_log")
    op.drop_table("brand_invocations")
    op.drop_table("brand_option_cards")
    op.drop_table("brand_treatment_steps")
    op.drop_table("brand_skill_stack")
    op.drop_table("brand_adspec_items")
    op.drop_table("brand_hypotheses")
    op.drop_table("brand_journeys")
    op.drop_table("brand_facts")
    op.drop_table("brands")
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("ck_projects_mode", type_="check")
        batch.drop_column("mode")
