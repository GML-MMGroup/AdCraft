"""Bounded brand capability invocation and validated persistence.

Each brand creative operation loads exactly one capability. Python validates
every structured output against the slot schema and option constraints before
anything is persisted, and appends the decision log in the same transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Literal, cast
from uuid import uuid4

from sqlalchemy import select, text as sql_text

from app.core.config import Settings, get_settings
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import (
    BrandDecisionLogEntryV1,
    BrandJourneyStateV1,
    BrandOptionCardV1,
    BrandShortOptionV1,
    BrandSlotValueV1,
    BrandStage,
    BrandStrategyOutputV1,
    BrandTreatmentSubstep,
    CreativeHypothesisCandidateV1,
    CreativeStrategyOutputV1,
    CreativeTreatmentOutputV1,
    CreativeTreatmentStepOutputV1,
    SlotProvenance,
    SkillStackEntryV1,
    SkillStackV1,
    TreatmentStepResultV1,
)
from app.persistence.models import BrandOptionCardRow
from app.services.brand_journey_state import (
    TREATMENT_SUBSTEP_ORDER,
    advance_brand_stage,
    advance_treatment_substep,
)
from app.services.brand_slot_schema import (
    missing_required_slots,
    slots_for_stage,
    validate_slot_values,
)
from app.services.creative_method_skill_catalog import CreativeMethodSkillCatalogService
from app.services.creative_method_skill_catalog import creative_method_seed_dir
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationSpec,
)

_LogAction = Literal["select", "reject", "fusion", "recommend", "edit", "confirm", "lock"]


class BrandCapabilityInvocationService:
    """Invoke one bounded capability and persist its validated output."""

    def __init__(
        self,
        database: V2Database,
        *,
        settings: Settings | None = None,
        generation_runtime: StructuredGenerationRuntime | None = None,
    ) -> None:
        self._database = database
        self._settings = settings or get_settings()
        self._runtime = generation_runtime or StructuredGenerationRuntime(settings=self._settings)
        self._repository = BrandDecisionRepository(database)
        self._catalog = CreativeMethodSkillCatalogService(database, creative_method_seed_dir())

    def _workflow_response_locale(self, brand_id: str) -> str:
        """Resolve the conversation response locale for one brand's workflow."""

        workflow_id = self._repository.workflow_id_for_brand(brand_id)
        if workflow_id is None:
            return "und"
        try:
            with self._database.engine.connect() as connection:
                row = connection.execute(
                    sql_text(
                        "SELECT response_locale FROM agent_canvas_guidance_sessions "
                        "WHERE workflow_id = :workflow_id LIMIT 1"
                    ),
                    {"workflow_id": workflow_id},
                ).first()
                if row and row[0] and str(row[0]) != "und":
                    return str(row[0])
                metadata_rows = connection.execute(
                    sql_text(
                        "SELECT metadata_json FROM agent_canvas_chat_entries "
                        "WHERE workflow_id = :workflow_id "
                        "AND entry_type = 'message' "
                        "AND speaker = 'adcraft_video_agent' "
                        "ORDER BY sequence_no DESC LIMIT 32"
                    ),
                    {"workflow_id": workflow_id},
                ).scalars()
                for metadata_json in metadata_rows:
                    try:
                        metadata = json.loads(str(metadata_json))
                    except json.JSONDecodeError:
                        continue
                    locale = metadata.get("response_locale") if isinstance(metadata, dict) else None
                    if isinstance(locale, str) and locale and locale != "und":
                        return locale
                return str(row[0]) if row and row[0] else "und"
        except Exception:  # noqa: BLE001 - locale lookup is best-effort
            return "und"

    # ---- Slot question -----------------------------------------------------

    def run_slot_question(
        self,
        brand_id: str,
        stage: BrandStage,
        *,
        model_id: str | None = None,
        output: BrandStrategyOutputV1 | None = None,
    ) -> BrandOptionCardV1:
        """Run one slot-question capability operation and persist it."""

        values = self._repository.get_slot_values(brand_id)
        validate_slot_values(values)
        journey = self._repository.get_journey(brand_id)
        if journey is None:
            raise _not_found()
        if journey.stage != stage:
            raise _stage_mismatch()
        if output is None:
            spec = StructuredGenerationSpec[BrandStrategyOutputV1](
                stage_name="brand_slot_question",
                contract_name="BrandStrategyOutputV1",
                model_id=model_id or self._settings.llm_creative_model,
                system_prompt=_BRAND_STRATEGY_PROMPT,
                input_payload={
                    "stage": stage,
                    "response_locale": self._workflow_response_locale(brand_id),
                    "slots": [
                        {
                            "slot_id": slot.slot_id,
                            "question": slot.question,
                            "required": slot.required,
                        }
                        for slot in slots_for_stage(stage)
                    ],
                    "confirmed_values": [value.model_dump(mode="json") for value in values],
                },
                output_model=BrandStrategyOutputV1,
                quality_validator=lambda out: _validate_strategy(out, stage),
            )
            output = self._runtime.run(spec).output
        card = output.question_card
        if card is None:
            raise _card_invalid("Brand strategy output requires one question card.")
        _validate_card(card, stage)
        card = self._namespace_colliding_card_id(brand_id, card)
        validate_slot_values(output.slot_values)
        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            self._repository.upsert_slot_values_in_transaction(
                connection, brand_id, output.slot_values
            )
            self._repository.save_option_card_in_transaction(connection, brand_id, card)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage=stage,
                action="recommend",
                target_type="option_card",
                target_id=card.card_id,
                detail={"question": card.question},
                now=now,
            )
        return card

    def _namespace_colliding_card_id(
        self,
        brand_id: str,
        card: BrandOptionCardV1,
    ) -> BrandOptionCardV1:
        """Prevent model-provided card IDs from colliding across brands."""

        with self._database.engine.connect() as connection:
            owner = connection.execute(
                select(BrandOptionCardRow.brand_id).where(
                    BrandOptionCardRow.card_id == card.card_id
                )
            ).scalar_one_or_none()
        if owner is None or str(owner) == brand_id:
            return card
        return card.model_copy(update={"card_id": f"{brand_id}_{card.card_id}"})

    # ---- Slot selection ----------------------------------------------------

    def apply_slot_selection(
        self,
        brand_id: str,
        *,
        card_id: str,
        option_id: str,
        value_text: str,
        provenance: SlotProvenance,
    ) -> None:
        """Commit the user choice for the open card and advance when done."""

        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id:
                raise _stage_mismatch()
            if not any(option.option_id == option_id for option in card.options):
                raise _card_invalid("Selected option is not on the open card.")
            slot_id = card.target_slot_id
            if slot_id is None:
                raise _card_invalid("Card does not target a slot.")
            self._repository.upsert_slot_values_in_transaction(
                connection,
                brand_id,
                (
                    BrandSlotValueV1(
                        slot_id=slot_id,
                        stage=card.stage,
                        value=value_text,
                        provenance=provenance,
                    ),
                ),
            )
            self._repository.resolve_card_in_transaction(connection, brand_id, card_id)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage=card.stage,
                action="select",
                target_type="option",
                target_id=option_id,
                detail={"card_id": card_id, "slot_id": slot_id},
                now=now,
            )
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is not None and card.stage == journey.stage:
                values = self._repository.get_slot_values_in_transaction(connection, brand_id)
                if not missing_required_slots(card.stage, values):
                    self._repository.save_journey_in_transaction(
                        connection,
                        brand_id,
                        advance_brand_stage(journey),
                    )

    # ---- Hypotheses --------------------------------------------------------

    def run_hypotheses(
        self,
        brand_id: str,
        *,
        model_id: str | None = None,
        output: CreativeStrategyOutputV1 | None = None,
    ) -> tuple[CreativeHypothesisCandidateV1, ...]:
        journey = self._repository.get_journey(brand_id)
        if journey is None or journey.stage != "hypothesis":
            raise _stage_mismatch()
        if output is None:
            spec = StructuredGenerationSpec[CreativeStrategyOutputV1](
                stage_name="brand_hypothesis",
                contract_name="CreativeStrategyOutputV1",
                model_id=model_id or self._settings.llm_creative_model,
                system_prompt=_CREATIVE_STRATEGY_PROMPT,
                input_payload={
                    "skills": list(self._catalog.injection_summaries()),
                    "response_locale": self._workflow_response_locale(brand_id),
                    "confirmed_values": [
                        value.model_dump(mode="json")
                        for value in self._repository.get_slot_values(brand_id)
                    ],
                },
                output_model=CreativeStrategyOutputV1,
            )
            output = self._runtime.run(spec).output
        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            self._repository.replace_hypotheses_in_transaction(
                connection, brand_id, output.candidates
            )
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="hypothesis",
                action="recommend",
                target_type="hypothesis_batch",
                target_id=None,
                detail={"count": len(output.candidates)},
                now=now,
            )
        return output.candidates

    def apply_hypothesis_selection(self, brand_id: str, hypothesis_id: str) -> None:
        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is None or journey.stage != "hypothesis":
                raise _stage_mismatch()
            self._repository.select_hypothesis_in_transaction(connection, brand_id, hypothesis_id)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="hypothesis",
                action="select",
                target_type="hypothesis",
                target_id=hypothesis_id,
                detail={},
                now=now,
            )
            self._repository.save_journey_in_transaction(
                connection, brand_id, advance_brand_stage(journey)
            )

    def run_hypothesis_question(
        self,
        brand_id: str,
        *,
        model_id: str | None = None,
        output: CreativeStrategyOutputV1 | None = None,
    ) -> BrandOptionCardV1:
        """Persist the hypothesis candidates and return their three-option card."""

        journey = self._repository.get_journey(brand_id)
        if journey is None or journey.stage != "hypothesis":
            raise _stage_mismatch()
        candidates = self.run_hypotheses(brand_id, model_id=model_id, output=output)
        card = BrandOptionCardV1(
            card_id=f"hypothesis_candidates_{journey.stage_revision}",
            stage="hypothesis",
            stage_revision=journey.stage_revision,
            target_slot_id=None,
            question=self._hypothesis_question(brand_id),
            options=tuple(
                BrandShortOptionV1(
                    option_id=candidate.candidate_id,
                    label=candidate.label,
                    why=candidate.why,
                )
                for candidate in candidates
            ),
        )
        _validate_card(card, "hypothesis")
        return card

    def _hypothesis_question(self, brand_id: str) -> str:
        if self._workflow_response_locale(brand_id).lower().startswith("zh"):
            return "哪一个创意假设应该主导这次广告？"
        return "Which creative hypothesis should lead the campaign?"

    # ---- Skill stack -------------------------------------------------------

    def run_skill_stack_question(self, brand_id: str) -> BrandOptionCardV1:
        """Persist a recommended skill stack and expose its confirmation card."""

        journey = self._repository.get_journey(brand_id)
        if journey is None or journey.stage != "skill-stack":
            raise _stage_mismatch()
        if self._repository.get_skill_stack(brand_id) is None:
            stack = self._recommended_skill_stack(brand_id)
            now = datetime.now(timezone.utc)
            with self._database.engine.begin() as connection:
                self._repository.replace_skill_stack_in_transaction(connection, brand_id, stack)
                self._append_log(
                    connection,
                    brand_id=brand_id,
                    stage="skill-stack",
                    action="recommend",
                    target_type="skill_stack",
                    target_id=None,
                    detail={"entry_count": len(stack.entries)},
                    now=now,
                )
        card = BrandOptionCardV1(
            card_id=f"{brand_id}_skill_stack_{journey.stage_revision}",
            stage="skill-stack",
            stage_revision=journey.stage_revision,
            target_slot_id=None,
            question=self._skill_stack_question(brand_id),
            options=self._skill_stack_options(brand_id),
        )
        _validate_card(card, "skill-stack")
        with self._database.engine.begin() as connection:
            self._repository.save_option_card_in_transaction(connection, brand_id, card)
        return card

    def apply_skill_stack_selection(
        self,
        brand_id: str,
        *,
        card_id: str,
        option_id: str,
    ) -> None:
        """Confirm the recommended stack and advance to the treatment stage."""

        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "skill-stack":
                raise _stage_mismatch()
            if not any(option.option_id == option_id for option in card.options):
                raise _card_invalid("Selected option is not on the open card.")
            self._repository.resolve_card_in_transaction(connection, brand_id, card_id)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="skill-stack",
                action="confirm",
                target_type="skill_stack",
                target_id=option_id,
                detail={"card_id": card_id},
                now=now,
            )
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is None:
                raise _not_found()
            self._repository.save_journey_in_transaction(
                connection, brand_id, advance_brand_stage(journey)
            )

    def _recommended_skill_stack(self, brand_id: str) -> SkillStackV1:
        """Choose deterministic creative and audiovisual skills from current decisions."""

        with self._database.engine.connect() as connection:
            hypotheses = self._repository.get_hypotheses_in_transaction(connection, brand_id)
            selected_id = self._repository.get_selected_hypothesis_id_in_transaction(
                connection, brand_id
            )
        selected = next((item for item in hypotheses if item.candidate_id == selected_id), None)
        haystack = " ".join(
            (selected.label, selected.mechanism, selected.hypothesis) if selected else ()
        ).lower()
        catalog = self._repository.list_creative_skills()
        methods = tuple(item for item in catalog if item["skill_kind"] == "creative_method")
        matching = next(
            (
                item
                for item in methods
                if str(item["skill_id"]).replace("-", " ") in haystack
                or str(item["title"]).lower() in haystack
            ),
            methods[0] if methods else None,
        )
        entries: list[SkillStackEntryV1] = []
        if matching is not None:
            entries.append(
                SkillStackEntryV1(
                    skill_kind="creative_method",
                    skill_id=str(matching["skill_id"]),
                    title=str(matching["title"]),
                )
            )
        style = next(
            (
                value.value
                for value in self._repository.get_slot_values(brand_id)
                if value.slot_id == "adspec_creative_style"
            ),
            None,
        )
        if style:
            entries.append(
                SkillStackEntryV1(
                    skill_kind="audiovisual_style",
                    skill_id=f"style_{sha256(style.encode()).hexdigest()[:12]}",
                    title=style,
                )
            )
        return SkillStackV1(entries=tuple(entries))

    def _skill_stack_question(self, brand_id: str) -> str:
        if self._workflow_response_locale(brand_id).lower().startswith("zh"):
            return "请确认当前推荐的创意方法与视听风格组合，确认后进入创意方案。"
        return "Please confirm the recommended creative method and audiovisual style stack."

    def _skill_stack_options(self, brand_id: str) -> tuple[BrandShortOptionV1, ...]:
        if self._workflow_response_locale(brand_id).lower().startswith("zh"):
            return (
                BrandShortOptionV1(
                    option_id="confirm", label="确认推荐组合", why="按当前策略进入创意方案"
                ),
                BrandShortOptionV1(
                    option_id="adjust", label="稍后再调整", why="先保留组合并继续后续创意方案"
                ),
                BrandShortOptionV1(
                    option_id="delegate", label="交给 Agent 优化", why="由 Agent 按品牌目标优化组合"
                ),
            )
        return (
            BrandShortOptionV1(
                option_id="confirm",
                label="Confirm stack",
                why="Continue with the recommended stack",
            ),
            BrandShortOptionV1(
                option_id="adjust", label="Adjust later", why="Keep the stack and continue"
            ),
            BrandShortOptionV1(
                option_id="delegate",
                label="Let Agent optimize",
                why="Optimize for the campaign goal",
            ),
        )

    # ---- Treatment ---------------------------------------------------------

    def prepare_treatment_confirmation(self, brand_id: str) -> bool:
        """Stop completed treatment questions while retaining every user decision."""

        with self._database.engine.begin() as connection:
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is None or journey.stage != "treatment":
                return False
            steps = self._repository.get_treatment_steps_in_transaction(connection, brand_id)
            if not set(TREATMENT_SUBSTEP_ORDER).issubset(step.step_key for step in steps):
                return False
            connection.execute(
                BrandOptionCardRow.__table__.update()
                .where(BrandOptionCardRow.brand_id == brand_id, BrandOptionCardRow.status == "open")
                .values(status="superseded")
            )
            if journey.stage_status != "waiting_user":
                self._repository.save_journey_in_transaction(
                    connection,
                    brand_id,
                    journey.model_copy(update={"stage_status": "waiting_user"}),
                )
            return True

    def run_treatment_step(
        self,
        brand_id: str,
        *,
        model_id: str | None = None,
        output: CreativeTreatmentOutputV1 | None = None,
    ) -> CreativeTreatmentStepOutputV1:
        journey = self._repository.get_journey(brand_id)
        if journey is None or journey.stage != "treatment":
            raise _stage_mismatch()
        if self.prepare_treatment_confirmation(brand_id):
            raise V2PersistenceError(
                "brand_treatment_confirmation_required",
                "All treatment decisions are confirmed. Confirm the treatment lock to continue.",
                stage="brand_capability_invocation",
            )
        if output is None:
            spec = StructuredGenerationSpec[CreativeTreatmentOutputV1](
                stage_name="brand_treatment_step",
                contract_name="CreativeTreatmentOutputV1",
                model_id=model_id or self._settings.llm_creative_model,
                system_prompt=_CREATIVE_TREATMENT_PROMPT,
                input_payload={
                    "substep": journey.treatment_substep,
                    "response_locale": self._workflow_response_locale(brand_id),
                    "confirmed_values": [
                        value.model_dump(mode="json")
                        for value in self._repository.get_slot_values(brand_id)
                    ],
                },
                output_model=CreativeTreatmentOutputV1,
            )
            output = self._runtime.run(spec).output
        step = output.step
        now = datetime.now(timezone.utc)
        card = BrandOptionCardV1(
            card_id=f"bcard_{uuid4().hex[:12]}",
            stage="treatment",
            stage_revision=journey.stage_revision,
            target_slot_id=step.step_key,
            question=step.question,
            options=step.options,
        )
        _validate_card(card, "treatment")
        with self._database.engine.begin() as connection:
            self._repository.save_option_card_in_transaction(connection, brand_id, card)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="treatment",
                action="recommend",
                target_type="treatment_step",
                target_id=step.step_key,
                detail={"card_id": card.card_id},
                now=now,
            )
        return step

    def apply_treatment_selection(
        self,
        brand_id: str,
        *,
        card_id: str,
        option_id: str,
        selected_label: str,
        detail: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "treatment":
                raise _stage_mismatch()
            if not any(option.option_id == option_id for option in card.options):
                raise _card_invalid("Selected option is not on the open card.")
            step_key = cast_step(card.target_slot_id)
            self._repository.save_treatment_step_in_transaction(
                connection,
                brand_id,
                TreatmentStepResultV1(
                    step_key=step_key,
                    selected_label=selected_label,
                    detail=detail,
                    confirmed_at=now,
                ),
            )
            self._repository.resolve_card_in_transaction(connection, brand_id, card_id)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="treatment",
                action="select",
                target_type="treatment_step",
                target_id=step_key,
                detail={"card_id": card_id, "option_id": option_id},
                now=now,
            )
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is not None:
                self._repository.save_journey_in_transaction(
                    connection, brand_id, advance_treatment_substep(journey)
                )

    def lock_treatment(self, brand_id: str) -> BrandJourneyStateV1:
        """Lock the treatment once all eight sub-steps are confirmed.

        A lock that arrives early fails with `brand_slot_required_missing` and
        leaves the journey at its current sub-step.
        """

        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is None or journey.stage != "treatment":
                raise _stage_mismatch()
            steps = self._repository.get_treatment_steps_in_transaction(connection, brand_id)
            confirmed = {step.step_key for step in steps}
            missing = [key for key in TREATMENT_SUBSTEP_ORDER if key not in confirmed]
            if missing:
                raise V2PersistenceError(
                    "brand_slot_required_missing",
                    "Treatment lock requires all eight sub-steps; missing: " + ", ".join(missing),
                    stage="brand_capability_invocation",
                )
            locked = advance_brand_stage(journey)
            connection.execute(
                BrandOptionCardRow.__table__.update()
                .where(BrandOptionCardRow.brand_id == brand_id, BrandOptionCardRow.status == "open")
                .values(status="superseded")
            )
            self._repository.save_journey_in_transaction(connection, brand_id, locked)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="treatment",
                action="lock",
                target_type="treatment",
                target_id=None,
                detail={"stage": locked.stage},
                now=now,
            )
        return locked

    # ---- helpers -----------------------------------------------------------

    def _append_log(
        self,
        connection,
        *,
        brand_id: str,
        stage: BrandStage,
        action: str,
        target_type: str,
        target_id: str | None,
        detail: dict[str, object],
        now: datetime,
    ) -> None:
        self._repository.append_decision_log_in_transaction(
            connection,
            BrandDecisionLogEntryV1(
                log_id=f"blog_{uuid4().hex[:16]}",
                stage=stage,
                action=cast(_LogAction, action),
                target_type=target_type,
                target_id=target_id,
                detail=detail,
                created_at=now,
            ),
            brand_id=brand_id,
        )


def _validate_strategy(output: BrandStrategyOutputV1, stage: BrandStage) -> None:
    if output.question_card is not None and output.question_card.stage != stage:
        raise ValueError("Question card does not match the current stage.")


def _validate_card(card: BrandOptionCardV1, stage: BrandStage) -> None:
    if card.stage != stage:
        raise _card_invalid("Option card stage does not match the current stage.")


def cast_step(slot_id: str | None) -> BrandTreatmentSubstep:
    valid = {
        "hook",
        "story",
        "character",
        "scene",
        "visual",
        "camera",
        "editing",
        "sound",
    }
    if slot_id not in valid:
        raise _card_invalid("Treatment card does not target a treatment sub-step.")
    return cast(BrandTreatmentSubstep, slot_id)


def _not_found() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_decision_not_found",
        "Brand state not found.",
        stage="brand_capability_invocation",
    )


def _stage_mismatch() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_stage_action_mismatch",
        "Stage action does not match the current brand stage.",
        stage="brand_capability_invocation",
    )


def _card_invalid(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "brand_option_card_invalid",
        message,
        stage="brand_capability_invocation",
    )


_BRAND_STRATEGY_PROMPT = (
    "You are the Brand Strategy capability of the AdCraft Brand Professional Mode. "
    "Collect one slot at a time using exactly three short options."
    " The input_payload response_locale gives the user's conversation language;"
    " write question and option text in that language."
)
_CREATIVE_STRATEGY_PROMPT = (
    "You are the Creative Strategy capability of the AdCraft Brand Professional "
    "Mode. Diverge 8-12 directions internally and return exactly 3 candidates."
    " The input_payload response_locale gives the user's conversation language;"
    " write candidate text in that language."
)
_CREATIVE_TREATMENT_PROMPT = (
    "You are the Creative Treatment capability of the AdCraft Brand Professional "
    "Mode. Propose exactly three short options for the current treatment step."
    " The input_payload response_locale gives the user's conversation language;"
    " write question and option text in that language."
)
