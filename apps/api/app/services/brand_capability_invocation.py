"""Bounded brand capability invocation and validated persistence.

Each brand creative operation loads exactly one capability. Python validates
every structured output against the slot schema and option constraints before
anything is persisted, and appends the decision log in the same transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Literal, cast
from uuid import uuid4

from sqlalchemy import select, text as sql_text

from app.core.config import Settings, get_settings
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import (
    AdSpecItemV1,
    BrandDecisionLogEntryV1,
    BrandJourneyStateV1,
    BrandOptionCardV1,
    BrandShortOptionV1,
    BrandSlotValueV1,
    BrandStage,
    BrandStrategyOutputV1,
    BrandTreatmentSubstep,
    BrandCreativeMethodCatalogV1,
    BrandSkillRecommendationsV1,
    BrandSkillSelectionRequestV1,
    CreativeHypothesisCandidateV1,
    CreativeStrategyOutputV1,
    CreativeTreatmentOutputV1,
    CreativeTreatmentStepOutputV1,
    SlotProvenance,
    SkillStackV1,
    TreatmentStepResultV1,
)
from app.persistence.models import BrandOptionCardRow
from app.services.brand_skill_stack import BrandSkillStackService
from app.services.brand_journey_state import (
    TREATMENT_SUBSTEP_ORDER,
    advance_brand_stage,
    advance_treatment_substep,
)
from app.services.brand_slot_schema import (
    missing_required_slots,
    resolve_slot,
    slot_value_kind,
    slots_for_stage,
    validate_slot_values,
)
from app.services.creative_method_skill_catalog import (
    CreativeMethodSkillCatalogService,
    creative_method_seed_dir,
)
from app.services.agent_canvas_video_skills import VideoSkillRegistry
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)

_LogAction = Literal["select", "reject", "fusion", "recommend", "edit", "confirm", "lock"]

# AdSpec execution dimensions.  These are the downstream choices the contract
# either fixes, leaves open, or asks the Agent to offer several versions of.
_ADSPEC_EXECUTION_KEYS: tuple[str, ...] = (
    "hook",
    "character",
    "scene",
    "product_reveal",
    "location",
    "wardrobe",
    "narration",
)

_ADSPEC_PRESET_STATES: dict[str, dict[str, str]] = {
    # PRD 8.6 default: the Agent offers several concrete Hooks, characters,
    # scenes and product reveals, while execution details stay open.
    "recommended": {
        "hook": "variable",
        "character": "variable",
        "scene": "variable",
        "product_reveal": "variable",
        "location": "open",
        "wardrobe": "open",
        "narration": "open",
    },
    "locked": {key: "locked" for key in _ADSPEC_EXECUTION_KEYS},
    "open": {key: "open" for key in _ADSPEC_EXECUTION_KEYS},
}

_ADSPEC_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "campaign_goal": "广告目标",
        "audience": "受众",
        "core_message": "核心信息",
        "core_insight": "核心洞察",
        "core_creative": "核心创意",
        "product_role": "产品角色",
        "hook_requirement": "Hook 要求",
        "brand_boundary": "品牌边界",
        "production_format": "制作规格",
        "hook": "具体 Hook",
        "character": "角色",
        "scene": "场景",
        "product_reveal": "产品第一次出现方式",
        "location": "地点",
        "wardrobe": "服装细节",
        "narration": "是否使用旁白",
    },
    "en": {
        "campaign_goal": "Advertising goal",
        "audience": "Audience",
        "core_message": "Core message",
        "core_insight": "Core insight",
        "core_creative": "Core creative",
        "product_role": "Product role",
        "hook_requirement": "Hook requirement",
        "brand_boundary": "Brand boundary",
        "production_format": "Production format",
        "hook": "Concrete Hook",
        "character": "Character",
        "scene": "Scene",
        "product_reveal": "Product first appearance",
        "location": "Location",
        "wardrobe": "Wardrobe detail",
        "narration": "Narration",
    },
}


def _adspec_labels(response_locale: str) -> dict[str, str]:
    """Return the AdSpec label table for one response locale."""

    if response_locale.lower().startswith("zh"):
        return _ADSPEC_LABELS["zh"]
    return _ADSPEC_LABELS["en"]


def _adspec_line(label: str, value: str) -> str:
    return f"{label}: {value}"[:600]


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
        self._catalog = CreativeMethodSkillCatalogService(
            database,
            creative_method_seed_dir(),
        )
        self._video_skills = VideoSkillRegistry()

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
        slot_values = _with_declared_information_nature(output.slot_values)
        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            self._repository.upsert_slot_values_in_transaction(connection, brand_id, slot_values)
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
            slot = resolve_slot(card.stage, slot_id)
            self._repository.upsert_slot_values_in_transaction(
                connection,
                brand_id,
                (
                    BrandSlotValueV1(
                        slot_id=slot_id,
                        stage=card.stage,
                        value=value_text,
                        kind=slot_value_kind(slot, provenance),
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

    # ---- AdSpec ------------------------------------------------------------

    def run_adspec_question(self, brand_id: str) -> BrandOptionCardV1:
        """Project the confirmed authority into the AdSpec contract and ask to confirm it."""

        journey = self._repository.get_journey(brand_id)
        if journey is None or journey.stage != "adspec":
            raise _stage_mismatch()
        items = self._project_adspec_items(brand_id)
        now = datetime.now(timezone.utc)
        card = BrandOptionCardV1(
            card_id=f"{brand_id}_adspec_{journey.stage_revision}",
            stage="adspec",
            stage_revision=journey.stage_revision,
            target_slot_id=None,
            question=self._adspec_question(brand_id),
            options=self._adspec_options(brand_id),
        )
        _validate_card(card, "adspec")
        with self._database.engine.begin() as connection:
            self._repository.replace_adspec_items_in_transaction(connection, brand_id, items)
            self._repository.save_option_card_in_transaction(connection, brand_id, card)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="adspec",
                action="recommend",
                target_type="adspec",
                target_id=card.card_id,
                detail={
                    "state_counts": {
                        state: sum(1 for item in items if item.state == state)
                        for state in ("locked", "open", "variable")
                    }
                },
                now=now,
            )
        return card

    def apply_adspec_selection(
        self,
        brand_id: str,
        *,
        card_id: str,
        option_id: str,
    ) -> None:
        """Apply the chosen execution preset to the AdSpec contract and continue."""

        states = _ADSPEC_PRESET_STATES.get(option_id)
        if states is None:
            raise _card_invalid("AdSpec preset is not one of the published options.")
        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "adspec":
                raise _stage_mismatch()
            if not any(option.option_id == option_id for option in card.options):
                raise _card_invalid("Selected option is not on the open card.")
            self._repository.resolve_card_in_transaction(connection, brand_id, card_id)
            for item_key, state in states.items():
                self._repository.update_adspec_item_state_in_transaction(
                    connection, brand_id, item_key, state
                )
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="adspec",
                action="confirm" if option_id == "recommended" else "edit",
                target_type="adspec",
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

    def _project_adspec_items(self, brand_id: str) -> tuple[AdSpecItemV1, ...]:
        """Derive the creation contract from confirmed brand, campaign and creative authority."""

        labels = _adspec_labels(self._workflow_response_locale(brand_id))
        with self._database.engine.connect() as connection:
            slots = {
                value.slot_id: value.value
                for value in self._repository.get_slot_values_in_transaction(connection, brand_id)
            }
            hypotheses = self._repository.get_hypotheses_in_transaction(connection, brand_id)
            selected_id = self._repository.get_selected_hypothesis_id_in_transaction(
                connection, brand_id
            )
        selected = next((item for item in hypotheses if item.candidate_id == selected_id), None)
        items: list[AdSpecItemV1] = []

        def lock(item_key: str, value: str | None) -> None:
            if not value:
                return
            items.append(
                AdSpecItemV1(
                    item_key=item_key,
                    item_text=_adspec_line(labels[item_key], value),
                    state="locked",
                )
            )

        lock("campaign_goal", slots.get("campaign_goal"))
        lock("audience", slots.get("brand_audience"))
        lock("core_message", slots.get("brand_positioning"))
        if selected is not None:
            lock("core_insight", selected.insight)
            lock("core_creative", selected.hypothesis)
            lock("product_role", selected.product_role)
            lock("hook_requirement", selected.hook_mechanism)
        lock("brand_boundary", slots.get("brand_avoid"))
        production_format = " / ".join(
            value
            for value in (slots.get("campaign_duration"), slots.get("campaign_aspect_ratio"))
            if value
        )
        lock("production_format", production_format or None)
        items.extend(
            AdSpecItemV1(
                item_key=item_key,
                item_text=labels[item_key],
                state=_ADSPEC_PRESET_STATES["recommended"][item_key],
            )
            for item_key in _ADSPEC_EXECUTION_KEYS
        )
        return tuple(items)

    def _adspec_question(self, brand_id: str) -> str:
        if self._workflow_response_locale(brand_id).lower().startswith("zh"):
            return "请确认这份广告规格：哪些执行维度固定、开放或需要多个方案？"
        return (
            "Confirm this advertising spec: which execution dimensions stay fixed, "
            "open, or need several versions?"
        )

    def _adspec_options(self, brand_id: str) -> tuple[BrandShortOptionV1, ...]:
        if self._workflow_response_locale(brand_id).lower().startswith("zh"):
            return (
                BrandShortOptionV1(
                    option_id="recommended",
                    label="按推荐执行",
                    why="具体 Hook、角色、场景、产品首次出现由 Agent 各给多个方案",
                ),
                BrandShortOptionV1(
                    option_id="locked",
                    label="全部固定",
                    why="执行维度全部按当前方案锁定，下游不得改动",
                ),
                BrandShortOptionV1(
                    option_id="open",
                    label="全部开放",
                    why="执行维度全部交给下游自由发挥",
                ),
            )
        return (
            BrandShortOptionV1(
                option_id="recommended",
                label="Use the recommendation",
                why="The Agent offers several Hooks, characters, scenes and reveals",
            ),
            BrandShortOptionV1(
                option_id="locked",
                label="Lock everything",
                why="Freeze every execution dimension as the current plan states",
            ),
            BrandShortOptionV1(
                option_id="open",
                label="Open everything",
                why="Leave every execution dimension to downstream freedom",
            ),
        )

    # ---- Skill stack -------------------------------------------------------

    def run_skill_stack_question(self, brand_id: str) -> BrandOptionCardV1:
        """Persist a recommended skill stack and expose its confirmation card."""

        journey = self._repository.get_journey(brand_id)
        if journey is None or journey.stage != "skill-stack":
            raise _stage_mismatch()
        stack = self._repository.get_skill_stack(brand_id)
        if stack is None:
            stack = self._recommended_skill_stack(brand_id)
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
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            current = self._repository.get_journey_in_transaction(connection, brand_id)
            if (
                current is None
                or current.stage != "skill-stack"
                or current.stage_revision != journey.stage_revision
            ):
                raise _stage_mismatch()
            if self._repository.get_skill_stack_in_transaction(connection, brand_id) is None:
                self._repository.replace_skill_stack_in_transaction(connection, brand_id, stack)
                self._append_log(
                    connection,
                    brand_id=brand_id,
                    stage="skill-stack",
                    action="recommend",
                    target_type="skill_stack",
                    target_id=None,
                    detail=stack.model_dump(mode="json"),
                    now=datetime.now(timezone.utc),
                )
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

        if option_id == "adjust":
            raise V2PersistenceError(
                "brand_skill_selection_required",
                "Open the Skill selector and submit explicit Skill ids and versions.",
            )

        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "skill-stack":
                raise _stage_mismatch()
            if not any(option.option_id == option_id for option in card.options):
                raise _card_invalid("Selected option is not on the open card.")
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if (
                journey is None
                or journey.stage != "skill-stack"
                or journey.stage_revision != card.stage_revision
            ):
                raise _stage_mismatch()
            stack = self._repository.get_skill_stack_in_transaction(connection, brand_id)
            BrandSkillStackService(self._database).activate(
                connection, brand_id, stack or SkillStackV1(), card_id
            )
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
        """Ask one bounded Pi capability for catalog-grounded recommendations."""

        with self._database.engine.connect() as connection:
            hypotheses = self._repository.get_hypotheses_in_transaction(connection, brand_id)
            selected_id = self._repository.get_selected_hypothesis_id_in_transaction(
                connection, brand_id
            )
            adspec = self._repository.get_adspec_in_transaction(connection, brand_id)
        selected = next((item for item in hypotheses if item.candidate_id == selected_id), None)
        skills = BrandSkillStackService(self._database)
        spec = StructuredGenerationSpec[BrandSkillRecommendationsV1](
            stage_name="brand_skill_recommendation",
            operation="brand_skill_recommendation",
            contract_name="BrandSkillRecommendationsV1",
            model_id=self._settings.llm_creative_model,
            system_prompt="",
            output_model=BrandSkillRecommendationsV1,
            input_payload={
                **skills.recommendation_catalogs(),
                "response_locale": self._workflow_response_locale(brand_id),
                "confirmed_values": [
                    value.model_dump(mode="json")
                    for value in self._repository.get_slot_values(brand_id)
                ],
                "selected_hypothesis": selected.model_dump(mode="json") if selected else None,
                "adspec": adspec.model_dump(mode="json") if adspec else None,
            },
            trace_metadata={"workflow_id": self._repository.workflow_id_for_brand(brand_id)},
        )
        try:
            output = self._runtime.run(spec).output
        except StructuredGenerationRuntimeError as error:
            raise V2PersistenceError(
                "brand_skill_recommendation_unavailable",
                "Skill recommendations are unavailable. Retry the current step.",
                stage="brand_skill_recommendation",
            ) from error
        return skills.recommendation_stack(output)

    def creative_method_catalog(self) -> BrandCreativeMethodCatalogV1:
        return BrandSkillStackService(self._database).creative_method_catalog()

    def select_skills(self, brand_id: str, request: BrandSkillSelectionRequestV1) -> None:
        """Save or confirm a versioned selection with atomic style activation."""
        skills = BrandSkillStackService(self._database)
        with self._database.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if (
                journey is None
                or journey.stage != "skill-stack"
                or journey.stage_revision != request.expected_stage_revision
                or card is None
                or card.card_id != request.card_id
                or card.stage_revision != journey.stage_revision
            ):
                raise _stage_mismatch()
            previous = self._repository.get_skill_stack_in_transaction(connection, brand_id)
            stack = skills.selection_stack(
                request.creative_methods, request.audiovisual_style, previous
            )
            if request.confirm:
                skills.activate(connection, brand_id, stack, card.card_id)
            self._repository.replace_skill_stack_in_transaction(connection, brand_id, stack)
            self._repository.resolve_card_in_transaction(connection, brand_id, card.card_id)
            next_journey = (
                advance_brand_stage(journey)
                if request.confirm
                else journey.model_copy(update={"stage_revision": journey.stage_revision + 1})
            )
            self._repository.save_journey_in_transaction(connection, brand_id, next_journey)
            if not request.confirm:
                self._repository.save_option_card_in_transaction(
                    connection,
                    brand_id,
                    card.model_copy(
                        update={
                            "card_id": f"{brand_id}_skill_stack_{next_journey.stage_revision}",
                            "stage_revision": next_journey.stage_revision,
                        }
                    ),
                )
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="skill-stack",
                action="confirm" if request.confirm else "edit",
                target_type="skill_stack",
                target_id=card.card_id,
                detail=stack.model_dump(mode="json"),
                now=datetime.now(timezone.utc),
            )

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
                    option_id="adjust",
                    label="选择 Skills",
                    why="调整创意方法和视听风格，确认前不会继续",
                ),
                BrandShortOptionV1(
                    option_id="delegate",
                    label="采用当前组合",
                    why="确认当前推荐或调整后的组合并继续",
                ),
            )
        return (
            BrandShortOptionV1(
                option_id="confirm",
                label="Confirm stack",
                why="Continue with the recommended stack",
            ),
            BrandShortOptionV1(
                option_id="adjust", label="Choose Skills", why="Edit Skills before continuing"
            ),
            BrandShortOptionV1(
                option_id="delegate",
                label="Use the current stack",
                why="Confirm the current selection and continue",
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
                    **BrandSkillStackService(self._database).treatment_context(
                        brand_id, journey.treatment_substep
                    ),
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


def _with_declared_information_nature(
    values: tuple[BrandSlotValueV1, ...],
) -> tuple[BrandSlotValueV1, ...]:
    """Stamp each slot value with its declared nature instead of a default fact."""

    return tuple(
        value.model_copy(
            update={
                "kind": slot_value_kind(
                    resolve_slot(value.stage, value.slot_id),
                    value.provenance,
                )
            }
        )
        for value in values
    )


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
