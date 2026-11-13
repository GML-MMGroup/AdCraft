"""Deterministic, opt-in choice between guided Treatment and a complete screenplay."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.models import BrandDecisionLogRow
from app.schemas.brand_professional_mode import (
    BrandDecisionLogEntryV1,
    BrandOptionCardV1,
    BrandShortOptionV1,
)
from app.services.brand_question_state import BrandQuestionState, stale_context


class BrandScriptRouteService:
    def __init__(self, database: V2Database) -> None:
        self.database = database
        self.repository = BrandDecisionRepository(database)

    def question(self, brand_id: str, locale: str) -> BrandOptionCardV1:
        chinese = locale.lower().startswith("zh")
        with self.database.engine.begin() as connection:
            journey = self.repository.get_journey_in_transaction(connection, brand_id)
            if journey is None or journey.stage != "creative-route":
                raise stale_context()
            BrandQuestionState(self.database).claim(connection, brand_id, journey.stage_revision)
            existing = self.repository.get_open_card_in_transaction(connection, brand_id)
            if (
                existing
                and existing.stage == journey.stage
                and existing.stage_revision == journey.stage_revision
            ):
                return existing
            card = BrandOptionCardV1(
                card_id=f"{brand_id}_creative_route_{journey.stage_revision}",
                stage="creative-route",
                stage_revision=journey.stage_revision,
                question="广告规格已确认，接下来你想怎么创作？"
                if chinese
                else "Your ad specifications are confirmed. How would you like to proceed?",
                options=(
                    BrandShortOptionV1(
                        option_id="guided",
                        label="继续逐步完善创意方案"
                        if chinese
                        else "Develop the creative plan step by step",
                        why="沿用现有流程，逐项选择故事、人物、场景和视听方案，再进入制作。"
                        if chinese
                        else "Choose the story, cast, scenes and audiovisual direction through the existing guided process.",
                    ),
                    BrandShortOptionV1(
                        option_id="full-script",
                        label="直接生成完整剧本并进入制作"
                        if chinese
                        else "Write a complete script and start production",
                        why="根据已确认的内容生成分幕剧本，展示画面、台词和音效，然后自动进入制作。"
                        if chinese
                        else "Receive a complete timed screenplay with action, dialogue and sound, then automatically enter production.",
                    ),
                ),
            )
            self.repository.save_option_card_in_transaction(connection, brand_id, card)
            return card

    def select(self, brand_id: str, *, card_id: str, option_id: str) -> None:
        with self.database.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            journey = self.repository.get_journey_in_transaction(connection, brand_id)
            card = self.repository.get_open_card_in_transaction(connection, brand_id)
            if (
                journey is None
                or journey.stage != "creative-route"
                or card is None
                or card.card_id != card_id
                or card.stage_revision != journey.stage_revision
                or option_id not in {"guided", "full-script"}
            ):
                raise stale_context()
            early = self.repository.early_skills_confirmed_in_transaction(connection, brand_id)
            stage = "treatment" if option_id == "full-script" or early else "skill-stack"
            self.repository.resolve_card_in_transaction(connection, brand_id, card_id)
            self.repository.append_decision_log_in_transaction(
                connection,
                BrandDecisionLogEntryV1(
                    log_id=f"blog_{uuid4().hex}",
                    stage="creative-route",
                    action="select",
                    target_type="creative_route",
                    target_id=option_id,
                    detail={"card_id": card_id},
                    created_at=datetime.now(timezone.utc),
                ),
                brand_id=brand_id,
            )
            self.repository.save_journey_in_transaction(
                connection,
                brand_id,
                journey.model_copy(
                    update={
                        "stage": stage,
                        "stage_revision": journey.stage_revision + 1,
                        "treatment_substep": "hook" if stage == "treatment" else None,
                        "stage_status": "ready",
                    }
                ),
            )

    @staticmethod
    def full_script_selected(connection: Connection, brand_id: str) -> bool:
        return (
            connection.execute(
                select(BrandDecisionLogRow.log_id)
                .where(
                    BrandDecisionLogRow.brand_id == brand_id,
                    BrandDecisionLogRow.target_type == "creative_route",
                    BrandDecisionLogRow.target_id == "full-script",
                    BrandDecisionLogRow.action == "select",
                )
                .limit(1)
            ).first()
            is not None
        )
