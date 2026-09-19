"""Publish brand option cards as Agent-chat guided interactions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from sqlalchemy import select

from app.persistence.models import (
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidedInteractionRow,
)
from app.schemas.agent_canvas_creative_session import (
    CreativeGoalV2,
    GuidanceCompletionProjectionV2,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingV2,
    GuidedChoiceOptionV1,
    GuidedConceptChoiceV2,
)
from app.services.agent_canvas_production_journey import (
    initial_production_journey,
)
from app.schemas.brand_professional_mode import BrandOptionCardV1

if TYPE_CHECKING:
    from app.persistence.database import V2Database


_BRAND_GOAL = CreativeGoalV2(
    requested_output="video",
    delivery_scope="generated_media",
    summary="Brand professional mode guided production",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrandGuidedInteractionBridge:
    """Write durable guided interactions so brand cards render in the chat."""

    def __init__(self, database: "V2Database") -> None:
        self._database = database

    def ensure_session(self, workflow_id: str, response_locale: str) -> str:
        """Create or return the brand guidance session for one workflow."""

        with self._database.engine.begin() as connection:
            row = (
                connection.execute(
                    select(
                        AgentCanvasGuidanceSessionRow.session_id,
                        AgentCanvasGuidanceSessionRow.response_locale,
                    ).where(AgentCanvasGuidanceSessionRow.workflow_id == workflow_id)
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                session_id = str(row["session_id"])
                if response_locale != "und" and str(row["response_locale"] or "und") == "und":
                    connection.execute(
                        AgentCanvasGuidanceSessionRow.__table__.update()
                        .where(AgentCanvasGuidanceSessionRow.session_id == session_id)
                        .values(response_locale=response_locale)
                    )
                return session_id
        journey = initial_production_journey(())
        completion = GuidanceCompletionProjectionV2()
        now = _now_iso()
        with self._database.engine.begin() as connection:
            existing = connection.execute(
                select(AgentCanvasGuidanceSessionRow.session_id).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            session_id = f"guidance_{uuid4().hex}"
            connection.execute(
                AgentCanvasGuidanceSessionRow.__table__.insert().values(
                    session_id=session_id,
                    workflow_id=workflow_id,
                    status="active",
                    response_locale=response_locale,
                    creative_goal_json=_BRAND_GOAL.model_dump_json(),
                    element_decisions_json="[]",
                    creative_authority_json=None,
                    current_checkpoint_json=None,
                    narrative_direction=None,
                    current_topic_id=None,
                    active_proposal_id=None,
                    active_style_skill_run_id=None,
                    completion_json=completion.model_dump_json(),
                    journey_state_json=journey.model_dump_json(),
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            return session_id

    def publish_card_interaction(
        self,
        workflow_id: str,
        card: BrandOptionCardV1,
        response_locale: str,
    ) -> None:
        """Publish a brand card as an open concept-choice guided interaction."""

        session_id = self.ensure_session(workflow_id, response_locale)
        stage_revision = card.stage_revision
        capability_id = f"brand_{card.stage}"
        workflow_key = sha256(workflow_id.encode()).hexdigest()[:16]
        card_key = sha256(card.card_id.encode()).hexdigest()[:12]
        checkpoint_id = f"checkpoint_{workflow_key}_{capability_id}_{stage_revision}_{card_key}"
        interaction_id = f"interaction_{workflow_key}_{capability_id}_{stage_revision}_{card_key}"
        now = datetime.now(timezone.utc).astimezone(timezone.utc)
        now_iso = now.isoformat()
        title = card.question[:160]
        context = _brand_interaction_context(card.stage, response_locale)
        options = tuple(
            GuidedChoiceOptionV1(
                option_id=option.option_id,
                title=option.label[:64],
                summary=(option.why or "")[:240],
                recommended=(index == 0),
            )
            for index, option in enumerate(card.options)
        )
        content = GuidedConceptChoiceV2(
            proposal_id=None,
            # Brand Professional Mode is represented as one intake journey in
            # the generic guided-interaction contract.  The brand stage is
            # carried by capability_id and the authoritative card ID.
            stage="intake",
            stage_revision=stage_revision,
            action_id=card.card_id[:160],
            capability_id=capability_id[:80],
            options=options,
            allow_exclusion=False,
        )
        awaiting_id = f"awaiting_{sha256(interaction_id.encode()).hexdigest()[:32]}"
        awaiting = GuidanceAwaitingV2(
            awaiting_id=awaiting_id,
            workflow_id=workflow_id,
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            kind="concept_selection",
            requires_user_action=True,
            resume_policy="submit_interaction",
            interaction_id=interaction_id,
            stage="intake",
            stage_revision=stage_revision,
            created_at=now,
        )
        with self._database.engine.begin() as connection:
            existing = (
                connection.execute(
                    select(
                        AgentCanvasGuidedInteractionRow.status,
                        AgentCanvasGuidedInteractionRow.response_locale,
                        AgentCanvasGuidedInteractionRow.content_json,
                        AgentCanvasGuidedInteractionRow.revision,
                    ).where(AgentCanvasGuidedInteractionRow.interaction_id == interaction_id)
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None and str(existing["status"]) == "submitted":
                return
            if (
                existing is not None
                and str(existing["status"]) == "open"
                and str(existing["response_locale"] or "und") == response_locale
                and str(existing["content_json"] or "") == content.model_dump_json()
            ):
                return
            existing_open = existing is not None and str(existing["status"]) == "open"
            session_row = (
                connection.execute(
                    select(AgentCanvasGuidanceSessionRow).where(
                        AgentCanvasGuidanceSessionRow.session_id == session_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            session_revision = int(session_row["revision"]) if session_row else 1
            connection.execute(
                AgentCanvasGuidanceAwaitingRow.__table__.delete().where(
                    AgentCanvasGuidanceAwaitingRow.workflow_id == workflow_id
                )
            )
            interaction_values = {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "checkpoint_id": checkpoint_id,
                "kind": "concept_choice",
                "status": "open",
                "response_locale": response_locale,
                "expected_session_revision": session_revision,
                "title": title,
                "context": context,
                "content_json": content.model_dump_json(),
                "allowed_actions_json": json.dumps(["select", "custom"]),
                "submit_path": (
                    f"/api/v2/workflows/{workflow_id}/chat/interactions/{interaction_id}/submit"
                ),
                "updated_at": now_iso,
            }
            if existing_open:
                connection.execute(
                    AgentCanvasGuidedInteractionRow.__table__.update()
                    .where(AgentCanvasGuidedInteractionRow.interaction_id == interaction_id)
                    .values(
                        **interaction_values,
                        revision=int(existing["revision"] or 1) + 1,
                    )
                )
            else:
                connection.execute(
                    AgentCanvasGuidedInteractionRow.__table__.update()
                    .where(
                        AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                        AgentCanvasGuidedInteractionRow.status == "open",
                    )
                    .values(status="superseded", updated_at=now_iso)
                )
                connection.execute(
                    AgentCanvasGuidedInteractionRow.__table__.insert().values(
                        interaction_id=interaction_id,
                        **interaction_values,
                        revision=1,
                        created_at=now_iso,
                    )
                )
            connection.execute(
                AgentCanvasGuidanceAwaitingRow.__table__.insert().values(
                    awaiting_id=awaiting.awaiting_id,
                    workflow_id=awaiting.workflow_id,
                    session_id=awaiting.session_id,
                    checkpoint_id=awaiting.checkpoint_id,
                    kind=awaiting.kind,
                    requires_user_action=awaiting.requires_user_action,
                    resume_policy=awaiting.resume_policy,
                    interaction_id=awaiting.interaction_id,
                    node_ids_json="[]",
                    stage=awaiting.stage,
                    stage_revision=awaiting.stage_revision,
                    created_at=awaiting.created_at.isoformat(),
                )
            )

    def close_current_interaction(
        self, workflow_id: str, *, status: Literal["submitted", "superseded"] = "submitted"
    ) -> None:
        """Close the open interaction and awaiting for one workflow."""

        now_iso = _now_iso()
        with self._database.engine.begin() as connection:
            connection.execute(
                AgentCanvasGuidedInteractionRow.__table__.update()
                .where(
                    AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                    AgentCanvasGuidedInteractionRow.status == "open",
                )
                .values(status=status, updated_at=now_iso)
            )
            connection.execute(
                AgentCanvasGuidanceAwaitingRow.__table__.delete().where(
                    AgentCanvasGuidanceAwaitingRow.workflow_id == workflow_id
                )
            )


def _brand_interaction_context(stage: str, response_locale: str) -> str:
    """Render the short interaction context in the persisted response locale."""

    if response_locale.lower().startswith("zh"):
        stage_labels = {
            "brand-memory": "品牌记忆",
            "campaign": "营销方向",
            "hypothesis": "创意假设",
            "adspec": "广告规格",
            "skill-stack": "技能组合",
            "treatment": "创意方案",
            "production": "制作",
        }
        return f"品牌专业模式：请选择{stage_labels.get(stage, stage)}阶段的方向"
    return f"Brand professional mode selection for stage {stage}"
