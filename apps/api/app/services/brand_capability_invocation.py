"""Bounded brand capability invocation and validated persistence.

Each brand creative operation loads exactly one capability. Python validates
every structured output against the slot schema and option constraints before
anything is persisted, and appends the decision log in the same transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from hashlib import sha256
from typing import Literal, cast
import unicodedata
from uuid import uuid4

from sqlalchemy import select, text as sql_text
from sqlalchemy.engine import Connection

from app.core.config import Settings, get_settings
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.brand_answer_history import append_brand_answer_in_transaction
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import (
    AdSpecItemV1,
    BrandDecisionLogEntryV1,
    BrandJourneyStateV1,
    BrandOptionCardV1,
    BrandFormAnswerV1,
    BrandFormOptionV1,
    BrandFormRowV1,
    BrandFormV1,
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
    TreatmentCandidateV1,
)
from app.persistence.models import BrandDecisionLogRow, BrandOptionCardRow
from app.schemas.brand_treatment_generation import treatment_output_model
from app.services.brand_skill_stack import BrandSkillStackService
from app.services.brand_question_context import BrandQuestionContextService
from app.services.brand_question_policy import (
    validate_question_output,
    unresolved_required_slots,
    optional_question_targets,
)
from app.services.brand_question_state import BrandQuestionState, stale_context
from app.services.brand_journey_state import (
    TREATMENT_SUBSTEP_ORDER,
    advance_brand_stage,
    advance_treatment_substep,
)
from app.services.brand_slot_schema import (
    SLOT_SCHEMA_VERSION,
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
    StructuredPresentationTargetV1,
)
from app.persistence.agent_canvas_presentation_repository import PresentationStreamRepository
from app.services.agent_canvas_presentation import PresentationStreamPublisher
import logging

_LogAction = Literal["select", "reject", "fusion", "recommend", "edit", "confirm", "lock"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrandFormSubmissionResult:
    """Durable result of applying one Brand foundation form."""

    requested_slot_ids: tuple[str, ...] = ()
    previous_options_by_slot: dict[str, tuple[BrandFormOptionV1, ...]] | None = None


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
        "product_identity": "产品身份",
        "required_elements": "必须包含",
        "campaign_non_goals": "本次不强调",
        "campaign_platform": "投放平台",
        "campaign_cta": "行动引导",
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
        "product_identity": "Product identity",
        "required_elements": "Required elements",
        "campaign_non_goals": "Campaign non-goals",
        "campaign_platform": "Campaign platform",
        "campaign_cta": "Call to action",
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

_CUSTOM_CARD_ANSWER_MODE_INSTRUCTION = (
    " Answer mode: the user wrote their own idea in `user_requirements`. Every concrete instruction "
    "in it is mandatory for every candidate — including order of shots or events, what opens the "
    "step, which subject appears first, tone, and anything to include or avoid. Implement each one "
    "literally; never reorder, drop, soften, or substitute them. The three candidates may differ "
    "only in details the user left unspecified. Keep the user's wording as the core of the label."
)


def _adspec_labels(response_locale: str) -> dict[str, str]:
    """Return the AdSpec label table for one response locale."""

    if response_locale.lower().startswith("zh"):
        return _ADSPEC_LABELS["zh"]
    return _ADSPEC_LABELS["en"]


def _adspec_line(label: str, value: str) -> str:
    return f"{label}: {value}"


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
        self._presentation_publisher = PresentationStreamPublisher(
            PresentationStreamRepository(database)
        )

    def _run_with_presentation(
        self,
        spec: StructuredGenerationSpec,
        *,
        brand_id: str,
        stage: str,
        stage_revision: int,
        substep_or_slot: str,
    ):
        workflow_id = self._repository.workflow_id_for_brand(brand_id)
        if workflow_id is None:
            return self._runtime.run(spec), None
        generation_id = f"brand-gen:{brand_id}:{stage}:{stage_revision}:{substep_or_slot}"
        attempt = uuid4().hex
        idempotency_key = f"{generation_id}:{attempt}"
        stream_id = f"prs_{sha256(idempotency_key.encode('utf-8')).hexdigest()[:32]}"
        stream = self._presentation_publisher.create_assistant_stream(
            workflow_id=workflow_id,
            turn_id=generation_id,
            generation_id=generation_id,
            stream_id=stream_id,
            idempotency_key=idempotency_key,
        )
        if stream is not None:
            self._presentation_publisher.started(stream)
        targeted = replace(
            spec,
            presentation=StructuredPresentationTargetV1(
                workflow_id=workflow_id,
                stream_id=stream.stream_id if stream is not None else stream_id,
            ),
        )
        try:
            result = self._runtime.run(targeted)
        except Exception as error:
            if stream is not None:
                try:
                    self._presentation_publisher.fail(
                        stream,
                        str(getattr(error, "code", None) or "brand_generation_failed"),
                    )
                except Exception as presentation_error:  # noqa: BLE001
                    logger.warning(
                        "Brand presentation failure handling failed: %s", presentation_error
                    )
            raise
        return result, stream

    def _finish_presentation(
        self,
        stream,
        *,
        authoritative_id: str,
        content: str = "",
    ) -> None:
        if stream is None:
            return
        try:
            self._presentation_publisher.commit(
                stream,
                authoritative_id=authoritative_id,
                content=content,
            )
        except Exception as error:  # noqa: BLE001 - presentation is best effort
            logger.warning("Brand presentation completion failed: %s", error)

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
    ) -> BrandOptionCardV1 | None:
        """Run one slot-question capability operation and persist it."""

        state = BrandQuestionState(self._database)
        product_context = state.context.read(brand_id)
        if product_context.payload["journey"] is None:
            raise _not_found()
        journey = BrandJourneyStateV1.model_validate(product_context.payload["journey"])
        values = tuple(
            BrandSlotValueV1.model_validate(value)
            for value in (
                product_context.payload["confirmed_values"] + product_context.payload["assumptions"]
            )
        )
        validate_slot_values(values)
        if journey.stage != stage:
            raise _stage_mismatch()
        with self._database.engine.connect() as connection:
            delegated = state.delegated_slots(connection, brand_id)
            asked_optional = state.asked_optional_slots(connection, brand_id, stage)
        if output is None:
            existing = state.current_card(brand_id)
            if existing is not None:
                return existing
            if (
                not unresolved_required_slots(stage, values, delegated)
                and not optional_question_targets(stage, values, delegated, asked_optional)
                and state.sources_normalized(brand_id, product_context)
            ):
                output = BrandStrategyOutputV1()
        if output is None:
            spec = StructuredGenerationSpec[BrandStrategyOutputV1](
                stage_name="brand_slot_question",
                contract_name="BrandStrategyOutputV1",
                model_id=model_id or self._settings.llm_creative_model,
                system_prompt=_BRAND_STRATEGY_PROMPT,
                input_payload={
                    "product_context": product_context.payload,
                    "stage": stage,
                    "asked_optional_slots": sorted(asked_optional),
                    "optional_question_budget_remaining": max(0, 2 - len(asked_optional)),
                    "slot_schema_version": SLOT_SCHEMA_VERSION,
                    "delegated_slots": [
                        {"stage": key[0], "slot_id": key[1]} for key in sorted(delegated)
                    ],
                    "response_locale": self._workflow_response_locale(brand_id),
                    "slots": [
                        {
                            "stage": slot.stage,
                            "slot_id": slot.slot_id,
                            "question": slot.question,
                            "required": slot.required,
                        }
                        for slot in (*slots_for_stage("brand-memory"), *slots_for_stage("campaign"))
                    ],
                    "confirmed_values": [value.model_dump(mode="json") for value in values],
                },
                output_model=BrandStrategyOutputV1,
                trace_metadata={"workflow_id": product_context.workflow_id},
                quality_validator=lambda out: _validate_strategy(out, stage),
            )
            runtime_result, presentation_stream = self._run_with_presentation(
                spec,
                brand_id=brand_id,
                stage=stage,
                stage_revision=journey.stage_revision,
                substep_or_slot="question",
            )
            output = runtime_result.output
        else:
            presentation_stream = None
        card = output.question_card
        slot_values = validate_question_output(
            output,
            stage,
            product_context,
            values,
            delegated=delegated,
            asked_optional_slots=asked_optional,
        )
        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            state.claim(connection, brand_id, journey.stage_revision)
            state.require_snapshot(connection, brand_id, product_context)
            self._repository.upsert_slot_values_in_transaction(connection, brand_id, slot_values)
            next_journey = (
                advance_brand_stage(journey)
                if card is None
                else journey.model_copy(update={"stage_revision": journey.stage_revision + 1})
            )
            self._repository.save_journey_in_transaction(connection, brand_id, next_journey)
            if card is None:
                connection.execute(
                    BrandOptionCardRow.__table__.update()
                    .where(
                        BrandOptionCardRow.brand_id == brand_id,
                        BrandOptionCardRow.status == "open",
                    )
                    .values(status="superseded")
                )
            else:
                card = self._namespace_colliding_card_id(connection, brand_id, card)
                card = card.model_copy(update={"stage_revision": next_journey.stage_revision})
                self._repository.save_option_card_in_transaction(connection, brand_id, card)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage=stage,
                action="recommend",
                target_type="option_card",
                target_id=card.card_id if card else None,
                detail={
                    "question": card.question if card else None,
                    "target_slot_id": card.target_slot_id if card else None,
                    "question_impact": output.question_impact.model_dump(mode="json")
                    if output.question_impact
                    else None,
                    "slot_evidence": [
                        item.model_dump(mode="json") for item in output.slot_evidence
                    ],
                    "clarifications": [
                        item.model_dump(mode="json") for item in output.clarifications
                    ],
                    "normalized_input_digest": product_context.input_digest,
                    "context_digest": state.context.read_in_transaction(
                        connection, brand_id
                    ).digest,
                },
                now=now,
            )
        self._finish_presentation(
            presentation_stream,
            authoritative_id=card.card_id
            if card is not None
            else f"brand-gen:{brand_id}:{stage}:{journey.stage_revision}:question",
            content=card.question if card is not None else "",
        )
        return card

    def run_slot_form(
        self,
        brand_id: str,
        stage: Literal["brand-memory", "campaign"],
        *,
        model_id: str | None = None,
        output: BrandStrategyOutputV1 | None = None,
        requested_slot_ids: tuple[str, ...] | None = None,
        previous_options_by_slot: dict[str, tuple[BrandFormOptionV1, ...]] | None = None,
        round_id: str | None = None,
    ) -> BrandFormV1:
        """Generate a foundation form for unresolved slots.

        A supplemental round supplies only the slots for which the user asked
        for more choices.  Existing recommendations are carried into the new
        form so the user can compare them with the new recommendations.
        """

        state = BrandQuestionState(self._database)
        product_context = state.context.read(brand_id)
        journey = self._repository.get_journey(brand_id)
        if journey is None or journey.stage != stage:
            raise _stage_mismatch()
        expected_slots = slots_for_stage(stage)
        if requested_slot_ids is not None:
            requested = tuple(dict.fromkeys(requested_slot_ids))
            expected_by_id = {slot.slot_id: slot for slot in expected_slots}
            if not requested or any(slot_id not in expected_by_id for slot_id in requested):
                raise V2PersistenceError(
                    "brand_form_invalid",
                    "Requested Brand form slots are not valid for this stage.",
                    stage="brand_capability_invocation",
                )
            expected_slots = tuple(expected_by_id[slot_id] for slot_id in requested)
        if output is None:

            def build_spec() -> StructuredGenerationSpec[BrandStrategyOutputV1]:
                supplemental = requested_slot_ids is not None
                return StructuredGenerationSpec[BrandStrategyOutputV1](
                    stage_name="brand_slot_form",
                    contract_name="BrandStrategyOutputV1",
                    model_id=model_id or self._settings.llm_creative_model,
                    system_prompt=(
                        _BRAND_STRATEGY_PROMPT
                        + " For form_mode=true, return form_cards with one card for every supplied "
                        "slot in the requested stage; do not persist or assume any answer."
                        + (
                            " For supplemental_form_mode=true, return three recommendations per "
                            "supplied slot, including at least two genuinely new alternatives. "
                            "The supplied previous options may be repeated for comparison, but must "
                            "not be the entire response and new options must not be rewordings or copies."
                            if requested_slot_ids is not None
                            else ""
                        )
                        + (
                            " The structured validator will reject repeated alternatives and allow "
                            "one bounded repair; use that repair to replace repeated options with "
                            "genuinely new alternatives."
                            if supplemental
                            else ""
                        )
                    ),
                    input_payload={
                        "product_context": product_context.payload,
                        "stage": stage,
                        "form_mode": True,
                        "supplemental_form_mode": supplemental,
                        "supplemental_attempt_no": 0 if supplemental else None,
                        "response_locale": self._workflow_response_locale(brand_id),
                        "slot_schema_version": SLOT_SCHEMA_VERSION,
                        "slots": [
                            {
                                "stage": slot.stage,
                                "slot_id": slot.slot_id,
                                "question": slot.question,
                                "required": slot.required,
                            }
                            for slot in expected_slots
                        ],
                        "previous_options_by_slot": {
                            slot_id: [option.model_dump(mode="json") for option in options]
                            for slot_id, options in (previous_options_by_slot or {}).items()
                        },
                        "confirmed_values": [
                            value.model_dump(mode="json")
                            for value in self._repository.get_slot_values(brand_id)
                        ],
                    },
                    output_model=BrandStrategyOutputV1,
                    trace_metadata={"workflow_id": product_context.workflow_id},
                    validation_profile=(
                        "brand_form_supplemental_novelty_v1"
                        if supplemental
                        else "brand_form_slots_v1"
                    ),
                    validation_context=(
                        {
                            "requested_slot_ids": [slot.slot_id for slot in expected_slots],
                            "previous_options_by_slot": {
                                slot_id: [option.model_dump(mode="json") for option in options]
                                for slot_id, options in (previous_options_by_slot or {}).items()
                            },
                            "minimum_new_options": 2,
                        }
                        if supplemental
                        else {
                            "expected_slot_ids": [slot.slot_id for slot in expected_slots],
                        }
                    ),
                )

            runtime_result, presentation_stream = self._run_with_presentation(
                build_spec(),
                brand_id=brand_id,
                stage=stage,
                stage_revision=journey.stage_revision,
                substep_or_slot=(round_id or "initial"),
            )
            output = runtime_result.output
        else:
            presentation_stream = None
        cards = tuple(output.form_cards)
        by_slot = {card.target_slot_id: card for card in cards}
        try:
            _validate_form_cards(output, stage, expected_slots)
            if requested_slot_ids is not None:
                _validate_supplemental_options(
                    output,
                    previous_options_by_slot or {},
                    expected_slots,
                )
        except (ValueError, V2PersistenceError) as error:
            raise V2PersistenceError(
                "brand_form_generation_invalid",
                "Brand foundation form options were malformed.",
                stage="brand_capability_invocation",
            ) from error
        locale = self._workflow_response_locale(brand_id)
        is_zh = locale.lower().startswith("zh")
        custom_option_label = "其他（自定义）" if is_zh else "Other (custom)"
        try:
            rows = tuple(
                BrandFormRowV1(
                    question_id=slot.slot_id,
                    slot_id=slot.slot_id,
                    prompt=by_slot[slot.slot_id].question,
                    options=self._merge_form_options(
                        slot.slot_id,
                        tuple(
                            BrandFormOptionV1(
                                option_id=option.option_id,
                                label=option.label,
                                why=option.why,
                            )
                            for option in by_slot[slot.slot_id].options
                        ),
                        (previous_options_by_slot or {}).get(slot.slot_id, ()),
                    )
                    + (BrandFormOptionV1(option_id="custom", label=custom_option_label),),
                    custom_option_id="custom",
                    required=True,
                )
                for slot in expected_slots
            )
        except ValueError as error:
            raise V2PersistenceError(
                "brand_form_generation_invalid",
                "Brand foundation form rows were malformed.",
                stage="brand_capability_invocation",
            ) from error
        suffix = "initial"
        if requested_slot_ids is not None:
            identity = round_id or ",".join(slot.slot_id for slot in expected_slots)
            suffix = f"more_{sha256(identity.encode()).hexdigest()[:16]}"
        if is_zh:
            instructions = (
                "每个问题请选择一个选项。选择“其他（自定义）”可填写自己的答案。"
                if requested_slot_ids is None
                else "请对比已有和新增方案，为每个问题选择一个选项。选择“其他（自定义）”可要求更多方案或填写自己的答案。"
            )
        else:
            instructions = (
                "Choose one option for every row. Select Other (custom) to enter your own answer."
                if requested_slot_ids is None
                else "Compare the existing and new options, then choose one option for every row. Select Other (custom) to request more options or enter your own answer."
            )
        form = BrandFormV1(
            form_id=f"brand_form_{brand_id}_{stage}_{journey.stage_revision}_{suffix}",
            stage=stage,
            revision=journey.stage_revision,
            response_locale=locale,
            context_digest=product_context.digest,
            title="Brand Memory" if stage == "brand-memory" else "Campaign",
            instructions=instructions,
            rows=rows,
        )
        self._finish_presentation(
            presentation_stream,
            authoritative_id=form.form_id,
            content="\n".join(row.prompt for row in form.rows),
        )
        return form

    @staticmethod
    def _merge_form_options(
        slot_id: str,
        new_options: tuple[BrandFormOptionV1, ...],
        previous_options: tuple[BrandFormOptionV1, ...],
    ) -> tuple[BrandFormOptionV1, ...]:
        """Keep prior options and append distinct new recommendations."""

        merged: list[BrandFormOptionV1] = []
        labels: set[str] = set()
        option_ids: set[str] = set()
        for option in (*previous_options, *new_options):
            label_key = option.label.strip().casefold()
            if label_key in labels:
                continue
            option_id = option.option_id
            if option_id in option_ids:
                option_id = f"more_{sha256(f'{slot_id}:{option.label}'.encode()).hexdigest()[:12]}"
            if option_id in option_ids:
                continue
            merged.append(option.model_copy(update={"option_id": option_id}))
            labels.add(label_key)
            option_ids.add(option_id)
        return tuple(merged)

    def apply_form_submission(
        self,
        brand_id: str,
        *,
        form: BrandFormV1,
        answers: tuple[BrandFormAnswerV1, ...],
    ) -> BrandFormSubmissionResult:
        """Validate and atomically commit one foundation form submission."""

        if form.stage not in {"brand-memory", "campaign"}:
            raise _card_invalid("Only Brand Memory and Campaign can use a form.")
        answer_by_question = {answer.question_id: answer for answer in answers}
        if len(answer_by_question) != len(answers) or set(answer_by_question) != {
            row.question_id for row in form.rows
        }:
            raise V2PersistenceError(
                "brand_form_invalid",
                "A complete answer is required for every Brand form row.",
                stage="brand_capability_invocation",
            )
        intents = self._form_answer_intents(brand_id, form, answers)
        values: list[BrandSlotValueV1] = []
        requested_slot_ids: list[str] = []
        previous_options_by_slot: dict[str, tuple[BrandFormOptionV1, ...]] = {}
        for row in form.rows:
            answer = answer_by_question[row.question_id]
            option = next(
                (item for item in row.options if item.option_id == answer.selected_option_id),
                None,
            )
            if option is None:
                raise V2PersistenceError(
                    "brand_form_invalid",
                    "A selected Brand form option is not current.",
                    stage="brand_capability_invocation",
                )
            is_custom = option.option_id == row.custom_option_id
            if is_custom != (answer.custom_text is not None):
                raise V2PersistenceError(
                    "brand_form_invalid",
                    "Custom text is allowed only with the custom option.",
                    stage="brand_capability_invocation",
                )
            if is_custom and intents.get(row.question_id) == "request_more_options":
                requested_slot_ids.append(row.slot_id)
                previous_options_by_slot[row.slot_id] = tuple(
                    item for item in row.options if item.option_id != row.custom_option_id
                )
                continue
            value = answer.custom_text.strip() if is_custom and answer.custom_text else option.label
            if not value:
                raise V2PersistenceError(
                    "brand_form_invalid",
                    "A custom Brand form answer cannot be empty.",
                    stage="brand_capability_invocation",
                )
            slot = resolve_slot(form.stage, row.slot_id)
            values.append(
                BrandSlotValueV1(
                    slot_id=row.slot_id,
                    stage=form.stage,
                    value=value,
                    kind=slot_value_kind(slot, "user_confirmed"),
                    provenance="user_confirmed",
                )
            )
        now = datetime.now(timezone.utc)
        state = BrandQuestionState(self._database)
        with self._database.engine.begin() as connection:
            state.claim(connection, brand_id, form.revision)
            context_matches = (
                state.context.read_in_transaction(connection, brand_id).digest
                == form.context_digest
            )
            if not context_matches and not self._has_recoverable_more_options_submission(
                connection, brand_id, form.form_id
            ):
                raise stale_context()
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if (
                journey is None
                or journey.stage != form.stage
                or journey.stage_revision != form.revision
            ):
                raise stale_context()
            if values:
                self._repository.upsert_slot_values_in_transaction(
                    connection, brand_id, tuple(values)
                )
            if not requested_slot_ids:
                self._repository.save_journey_in_transaction(
                    connection, brand_id, advance_brand_stage(journey)
                )
            self._append_log(
                connection,
                brand_id=brand_id,
                stage=form.stage,
                action="confirm" if not requested_slot_ids else "edit",
                target_type="brand_form",
                target_id=form.form_id,
                detail={
                    "context_digest": form.context_digest,
                    "row_count": len(values),
                    "requested_more_options": requested_slot_ids,
                },
                now=now,
            )
        return BrandFormSubmissionResult(
            requested_slot_ids=tuple(requested_slot_ids),
            previous_options_by_slot=previous_options_by_slot or None,
        )

    @staticmethod
    def _has_recoverable_more_options_submission(
        connection: Connection,
        brand_id: str,
        form_id: str,
    ) -> bool:
        """Allow retrying a supplement request after its first generation failed."""

        detail_json = connection.execute(
            select(BrandDecisionLogRow.detail_json)
            .where(
                BrandDecisionLogRow.brand_id == brand_id,
                BrandDecisionLogRow.action == "edit",
                BrandDecisionLogRow.target_type == "brand_form",
                BrandDecisionLogRow.target_id == form_id,
            )
            .order_by(BrandDecisionLogRow.log_id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if detail_json is None:
            return False
        try:
            return bool(json.loads(str(detail_json)).get("requested_more_options"))
        except (TypeError, json.JSONDecodeError):
            return False

    def _form_answer_intents(
        self,
        brand_id: str,
        form: BrandFormV1,
        answers: tuple[BrandFormAnswerV1, ...],
    ) -> dict[str, Literal["answer", "request_more_options"]]:
        """Normalize custom text intent through the bounded Agent contract."""

        custom_answers = tuple(answer for answer in answers if answer.custom_text is not None)
        intents: dict[str, Literal["answer", "request_more_options"]] = {
            answer.question_id: "answer" for answer in answers if answer.custom_text is None
        }
        if not custom_answers:
            return intents
        context = BrandQuestionState(self._database).context.read(brand_id)
        try:
            spec = StructuredGenerationSpec[BrandStrategyOutputV1](
                stage_name="brand_form_answer_intent",
                contract_name="BrandStrategyOutputV1",
                model_id=self._settings.llm_creative_model,
                system_prompt=(
                    _BRAND_STRATEGY_PROMPT
                    + " Analyze each supplied custom Brand form answer. Return one form_answer_intents "
                    + "entry per supplied custom answer. Use request_more_options only when the user is "
                    + "asking for additional alternatives for that question; otherwise use answer. "
                    + "Do not generate options or change any slot value."
                ),
                input_payload={
                    "product_context": context.payload,
                    "stage": form.stage,
                    "answer_analysis_mode": True,
                    "response_locale": form.response_locale,
                    "form_rows": [row.model_dump(mode="json") for row in form.rows],
                    "answers": [answer.model_dump(mode="json") for answer in custom_answers],
                },
                output_model=BrandStrategyOutputV1,
                trace_metadata={"workflow_id": context.workflow_id},
                operation="brand_slot_form",
            )
            runtime_result, presentation_stream = self._run_with_presentation(
                spec,
                brand_id=brand_id,
                stage=form.stage,
                stage_revision=form.revision,
                substep_or_slot="answer-intent",
            )
            output = runtime_result.output
            self._finish_presentation(
                presentation_stream,
                authoritative_id=f"brand-form-intent:{form.form_id}",
            )
            for item in output.form_answer_intents:
                if item.question_id in {answer.question_id for answer in custom_answers}:
                    intents[item.question_id] = item.intent
        except (StructuredGenerationRuntimeError, V2PersistenceError):
            # A classification outage must preserve the established custom
            # answer path; it must not make form confirmation unavailable.
            pass
        return intents

    def _card_custom_text_intent(
        self,
        brand_id: str,
        card: BrandOptionCardV1,
        custom_text: str,
    ) -> tuple[Literal["answer", "request_more_options"], str | None]:
        """Classify one card custom value, preserving answer fallback semantics.

        Obvious requests for alternatives never depend on a model call, so a
        classifier outage cannot turn "再来几个方案" into an applied idea.
        """

        if obvious_more_options_request(custom_text):
            return "request_more_options", custom_text.strip()[:240]
        context = BrandQuestionState(self._database).context.read(brand_id)
        try:
            # ``brand_slot_form`` validates against ``BrandStrategyOutputV1``,
            # so the interpretation travels in its optional
            # ``card_custom_intent`` field, like ``form_answer_intents``.
            spec = StructuredGenerationSpec[BrandStrategyOutputV1](
                stage_name="brand_card_custom_text_intent",
                contract_name="BrandStrategyOutputV1",
                model_id=self._settings.llm_creative_model,
                system_prompt=(
                    _BRAND_STRATEGY_PROMPT
                    + " Analyze the supplied custom text typed into this Brand card. Return only "
                    + "card_custom_intent and leave every other field empty. Use intent=answer for the "
                    + "user's own idea, and request_more_options only when they ask for alternatives or a "
                    + "changed direction. Put a short direction in direction when present. Do not "
                    + "generate options or change any slot value."
                ),
                input_payload={
                    "product_context": context.payload,
                    "answer_analysis_mode": True,
                    "card": card.model_dump(mode="json"),
                    "custom_text": custom_text,
                    "response_locale": self._workflow_response_locale(brand_id),
                },
                output_model=BrandStrategyOutputV1,
                trace_metadata={"workflow_id": context.workflow_id},
                operation="brand_slot_form",
            )
            runtime_result, presentation_stream = self._run_with_presentation(
                spec,
                brand_id=brand_id,
                stage=card.stage,
                stage_revision=card.stage_revision,
                substep_or_slot="custom-intent",
            )
            self._finish_presentation(
                presentation_stream,
                authoritative_id=f"brand-card-custom-intent:{card.card_id}",
            )
            interpretation = runtime_result.output.card_custom_intent
            if interpretation is None:
                return "answer", None
            return interpretation.intent, interpretation.direction
        except Exception:  # noqa: BLE001 - classifier failure falls back to answer
            return "answer", None

    def generate_hypothesis_custom_candidates(
        self,
        brand_id: str,
        card: BrandOptionCardV1,
        *,
        custom_text: str,
        direction: str | None,
        count: Literal[1, 3],
    ) -> tuple[CreativeHypothesisCandidateV1, ...]:
        """Generate faithful hypothesis candidates for a card custom operation."""

        context = BrandQuestionContextService(self._database).read(brand_id)
        existing_options = [{"label": option.label, "why": option.why} for option in card.options]
        spec = StructuredGenerationSpec[CreativeStrategyOutputV1](
            stage_name="brand_hypothesis_custom",
            contract_name="CreativeStrategyOutputV1",
            model_id=self._settings.llm_creative_model,
            system_prompt=(
                _CREATIVE_STRATEGY_PROMPT
                + " Always return exactly three candidates."
                + _CUSTOM_CARD_ANSWER_MODE_INSTRUCTION
                + " In request_more_options mode do not repeat or "
                + "paraphrase existing options and use the supplied direction as guidance."
            ),
            input_payload={
                "product_context": context.payload,
                "response_locale": self._workflow_response_locale(brand_id),
                "custom_text_mode": "answer" if count == 1 else "request_more_options",
                **(
                    {"user_requirements": custom_text}
                    if count == 1
                    else {"direction": direction, "existing_options": existing_options}
                ),
            },
            # The ``brand_hypothesis`` contract requires exactly three candidates.
            output_model=CreativeStrategyOutputV1,
            trace_metadata={"workflow_id": context.workflow_id},
            operation="brand_hypothesis",
        )
        runtime_result, presentation_stream = self._run_with_presentation(
            spec,
            brand_id=brand_id,
            stage="hypothesis",
            stage_revision=card.stage_revision,
            substep_or_slot="user-idea" if count == 1 else "more-options",
        )
        output = runtime_result.output
        candidates = tuple(output.candidates)
        if len(candidates) < count:
            raise _card_invalid("Generated hypothesis options did not match the requested count.")
        candidates = candidates[:count]
        digest = sha256(
            f"{card.card_id}:{len(card.options)}:{custom_text}".encode("utf-8")
        ).hexdigest()[:16]
        normalized = tuple(
            candidate.model_copy(
                update={
                    "candidate_id": f"custom_{digest}_{index}",
                }
            )
            for index, candidate in enumerate(candidates, start=1)
        )
        self._finish_presentation(
            presentation_stream,
            authoritative_id=f"brand-hypothesis-custom:{card.card_id}:{digest}",
            content="\n".join(candidate.label for candidate in normalized),
        )
        return normalized

    def generate_treatment_custom_candidates(
        self,
        brand_id: str,
        card: BrandOptionCardV1,
        *,
        custom_text: str,
        direction: str | None,
        count: Literal[1, 3],
    ) -> tuple[TreatmentCandidateV1, ...]:
        """Generate and validate structured Treatment candidates for a card."""

        step_key = cast_step(card.target_slot_id)
        context = BrandQuestionContextService(self._database).read(brand_id)
        spec = StructuredGenerationSpec(
            stage_name="brand_treatment_custom",
            contract_name="CreativeTreatmentOutputV1",
            model_id=self._settings.llm_creative_model,
            system_prompt=(
                _CREATIVE_TREATMENT_PROMPT
                + " Always return exactly three options for the current step."
                + _CUSTOM_CARD_ANSWER_MODE_INSTRUCTION
                + " In request_more_options mode do "
                + "not repeat or paraphrase existing options and follow the supplied direction."
            ),
            input_payload={
                "product_context": context.payload,
                **BrandSkillStackService(self._database).treatment_context(brand_id, step_key),
                "substep": step_key,
                "response_locale": self._workflow_response_locale(brand_id),
                "custom_text_mode": "answer" if count == 1 else "request_more_options",
                **(
                    {
                        "user_requirements": custom_text,
                        "user_requirements_scope": "This Treatment step only",
                    }
                    if count == 1
                    else {
                        "direction": direction,
                        "existing_options": [
                            {"label": option.label, "why": option.why} for option in card.options
                        ],
                    }
                ),
            },
            # The ``brand_treatment_step`` contract publishes three options.
            output_model=treatment_output_model(step_key),
            trace_metadata={"workflow_id": context.workflow_id},
            operation="brand_treatment_step",
        )
        runtime_result, presentation_stream = self._run_with_presentation(
            spec,
            brand_id=brand_id,
            stage="treatment",
            stage_revision=card.stage_revision,
            substep_or_slot="user-idea" if count == 1 else "more-options",
        )
        output = runtime_result.output
        if output.step.step_key != step_key or len(output.step.options) < count:
            raise _card_invalid("Generated Treatment options did not match the current step.")
        selected_options = tuple(output.step.options[:count])
        for candidate in selected_options:
            candidate.detail.validate_step(step_key)
        digest = sha256(
            f"{card.card_id}:{len(card.options)}:{custom_text}".encode("utf-8")
        ).hexdigest()[:16]
        normalized = tuple(
            candidate.model_copy(update={"option_id": f"custom_{digest}_{index}"})
            for index, candidate in enumerate(selected_options, start=1)
        )
        self._finish_presentation(
            presentation_stream,
            authoritative_id=f"brand-treatment-custom:{card.card_id}:{digest}",
            content="\n".join(candidate.label for candidate in normalized),
        )
        return normalized

    def _namespace_colliding_card_id(
        self,
        connection: Connection,
        brand_id: str,
        card: BrandOptionCardV1,
    ) -> BrandOptionCardV1:
        """Prevent model-provided card IDs from colliding across brands."""

        owner = connection.execute(
            select(BrandOptionCardRow.brand_id).where(BrandOptionCardRow.card_id == card.card_id)
        ).scalar_one_or_none()
        if owner is None:
            return card
        candidate = f"{brand_id}_{card.card_id}"
        occupied = connection.execute(
            select(BrandOptionCardRow.card_id).where(BrandOptionCardRow.card_id == candidate)
        ).first()
        if str(owner) == brand_id or occupied or len(candidate) > 120:
            candidate = f"bcard_{uuid4().hex}"
        return card.model_copy(update={"card_id": candidate})

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
        state = BrandQuestionState(self._database)
        observed = self._repository.get_journey(brand_id)
        if observed is None:
            raise _not_found()
        with self._database.engine.begin() as connection:
            state.claim(connection, brand_id, observed.stage_revision)
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id:
                raise _stage_mismatch()
            if not state.card_is_current(connection, brand_id, card):
                raise stale_context()
            slot_id = card.target_slot_id
            if slot_id is None:
                raise _card_invalid("Card does not target a slot.")
            slot = resolve_slot(card.stage, slot_id)
            selected = next(
                (option for option in card.options if option.option_id == option_id), None
            )
            custom = selected is None and option_id == "custom"
            delegated = selected is None and option_id == "delegate"
            if custom:
                if not value_text.strip() or len(value_text) > 2048:
                    raise _card_invalid("A custom answer requires bounded nonempty text.")
                self._append_log(
                    connection,
                    brand_id=brand_id,
                    stage=card.stage,
                    action="select",
                    target_type="custom_answer",
                    target_id=card_id,
                    detail={"text": value_text, "slot_id": slot_id},
                    now=now,
                )
            else:
                if delegated:
                    selected = card.options[0]
                if selected is None:
                    raise _card_invalid("Selected option is not on the open card.")
                value_text = selected.label
                provenance = "agent_recommended" if delegated else "user_confirmed"
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
                detail={
                    "card_id": card_id,
                    "slot_id": slot_id,
                    "delegated": delegated,
                    "value": value_text,
                },
                now=now,
            )
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is not None and card.stage == journey.stage:
                values = self._repository.get_slot_values_in_transaction(connection, brand_id)
                self._repository.save_journey_in_transaction(
                    connection,
                    brand_id,
                    journey.model_copy(update={"stage_revision": journey.stage_revision + 1}),
                )
                delegated_slots = state.delegated_slots(connection, brand_id)
                if (
                    not custom
                    and not unresolved_required_slots(card.stage, values, delegated_slots)
                    and not optional_question_targets(
                        card.stage,
                        values,
                        delegated_slots,
                        state.asked_optional_slots(connection, brand_id, card.stage),
                    )
                ):
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
        product_context = BrandQuestionContextService(self._database).read(brand_id)
        if output is None:
            spec = StructuredGenerationSpec[CreativeStrategyOutputV1](
                stage_name="brand_hypothesis",
                contract_name="CreativeStrategyOutputV1",
                model_id=model_id or self._settings.llm_creative_model,
                system_prompt=_CREATIVE_STRATEGY_PROMPT,
                input_payload={
                    "product_context": product_context.payload,
                    "skills": list(self._catalog.injection_summaries()),
                    "response_locale": self._workflow_response_locale(brand_id),
                    "confirmed_values": [
                        value.model_dump(mode="json")
                        for value in self._repository.get_slot_values(brand_id)
                    ],
                },
                output_model=CreativeStrategyOutputV1,
                trace_metadata={"workflow_id": product_context.workflow_id},
            )
            runtime_result, presentation_stream = self._run_with_presentation(
                spec,
                brand_id=brand_id,
                stage="hypothesis",
                stage_revision=journey.stage_revision,
                substep_or_slot="candidates",
            )
            output = runtime_result.output
        else:
            presentation_stream = None
        now = datetime.now(timezone.utc)
        with self._database.engine.begin() as connection:
            state = BrandQuestionState(self._database)
            state.claim(connection, brand_id, journey.stage_revision)
            state.require_snapshot(connection, brand_id, product_context)
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
        self._finish_presentation(
            presentation_stream,
            authoritative_id=f"brand-hypothesis:{brand_id}:{journey.stage_revision}",
            content="\n".join(item.label for item in output.candidates),
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

    @staticmethod
    def _merge_card_options(
        card: BrandOptionCardV1,
        additions: tuple[BrandShortOptionV1, ...],
    ) -> tuple[BrandShortOptionV1, ...]:
        """Append distinct labels while preserving existing order and IDs."""

        merged = list(card.options)
        labels = {option.label.strip().casefold() for option in merged}
        option_ids = {option.option_id for option in merged}
        for option in additions:
            label_key = option.label.strip().casefold()
            if label_key in labels:
                continue
            option_id = option.option_id
            if option_id in option_ids:
                option_id = (
                    f"more_{sha256(f'{card.card_id}:{option.label}'.encode()).hexdigest()[:16]}"
                )
            while option_id in option_ids:
                option_id = f"more_{uuid4().hex[:16]}"
            merged.append(option.model_copy(update={"option_id": option_id}))
            labels.add(label_key)
            option_ids.add(option_id)
        return tuple(merged)

    def apply_hypothesis_custom_candidate(
        self,
        brand_id: str,
        *,
        card_id: str,
        candidate: CreativeHypothesisCandidateV1,
    ) -> BrandOptionCardV1:
        """Append one hypothesis candidate and select it atomically."""

        now = datetime.now(timezone.utc)
        state = BrandQuestionState(self._database)
        observed = self._repository.get_journey(brand_id)
        if observed is None or observed.stage != "hypothesis":
            raise _stage_mismatch()
        with self._database.engine.begin() as connection:
            state.claim(connection, brand_id, observed.stage_revision)
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "hypothesis":
                raise _stage_mismatch()
            if not state.card_is_current(connection, brand_id, card):
                raise stale_context()
            additions = (
                BrandShortOptionV1(
                    option_id=candidate.candidate_id,
                    label=candidate.label,
                    why=candidate.why,
                ),
            )
            merged = self._merge_card_options(card, additions)
            if len(merged) > 12:
                raise _card_invalid("A Brand card can contain at most twelve options.")
            updated_card = card.model_copy(update={"options": merged})
            self._repository.append_hypotheses_in_transaction(connection, brand_id, (candidate,))
            self._repository.save_option_card_in_transaction(connection, brand_id, updated_card)
            self._repository.select_hypothesis_in_transaction(
                connection, brand_id, candidate.candidate_id
            )
            self._repository.resolve_card_in_transaction(connection, brand_id, card_id)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="hypothesis",
                action="select",
                target_type="hypothesis",
                target_id=candidate.candidate_id,
                detail={"card_id": card_id, "custom": True},
                now=now,
            )
            self._repository.save_journey_in_transaction(
                connection, brand_id, advance_brand_stage(observed)
            )
            return updated_card

    def append_hypothesis_options(
        self,
        brand_id: str,
        *,
        card_id: str,
        candidates: tuple[CreativeHypothesisCandidateV1, ...],
    ) -> BrandOptionCardV1:
        """Append generated hypothesis choices while leaving the card open."""

        now = datetime.now(timezone.utc)
        state = BrandQuestionState(self._database)
        with self._database.engine.begin() as connection:
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "hypothesis":
                raise _stage_mismatch()
            if not state.card_is_current(connection, brand_id, card):
                raise stale_context()
            existing_labels = {option.label.strip().casefold() for option in card.options}
            novel_candidates = tuple(
                candidate
                for candidate in candidates
                if candidate.label.strip().casefold() not in existing_labels
            )
            additions = tuple(
                BrandShortOptionV1(option_id=item.candidate_id, label=item.label, why=item.why)
                for item in novel_candidates
            )
            merged = self._merge_card_options(card, additions)
            if len(merged) > 12:
                raise _card_invalid("A Brand card can contain at most twelve options.")
            selected_candidates = tuple(
                candidate.model_copy(
                    update={
                        "candidate_id": next(
                            option.option_id for option in merged if option.label == candidate.label
                        )
                    }
                )
                for candidate in novel_candidates
                if any(option.label == candidate.label for option in merged)
            )
            self._repository.append_hypotheses_in_transaction(
                connection, brand_id, selected_candidates
            )
            updated_card = card.model_copy(update={"options": merged})
            self._repository.save_option_card_in_transaction(connection, brand_id, updated_card)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="hypothesis",
                action="recommend",
                target_type="option_card",
                target_id=card_id,
                detail={"card_id": card_id, "custom": "more_options", "count": len(candidates)},
                now=now,
            )
            return updated_card

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
        self.run_hypotheses(brand_id, model_id=model_id, output=output)
        # ``run_hypotheses`` persists the model candidates before returning.
        # The repository is the authority for the IDs shown to the user: a
        # provider may emit IDs that are normalized or namespaced during the
        # durable write.  Re-read the persisted rows so the card option IDs
        # are exactly the IDs accepted by ``select-hypothesis``.
        with self._database.engine.connect() as connection:
            candidates = self._repository.get_hypotheses_in_transaction(connection, brand_id)
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
        # Keep the generated hypothesis card in the same authoritative card
        # store as the later Brand stages.  This makes refreshes and concurrent
        # next-question requests reuse the exact persisted option IDs.
        with self._database.engine.begin() as connection:
            self._repository.save_option_card_in_transaction(connection, brand_id, card)
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
            current_items = {
                item.item_key: item
                for item in self._repository.get_adspec_in_transaction(connection, brand_id).items
            }
            for item_key, state in states.items():
                # A category label is not an execution decision. Keep its
                # existing open/variable state until concrete content exists.
                if state == "locked":
                    state = current_items[item_key].state
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
        lock("audience", slots.get("campaign_audience") or slots.get("brand_audience"))
        lock("core_message", slots.get("campaign_core_message") or slots.get("brand_product_focus"))
        lock("product_identity", slots.get("brand_product_identity"))
        lock("required_elements", slots.get("brand_required_elements"))
        lock("campaign_non_goals", slots.get("campaign_non_goals"))
        lock("campaign_platform", slots.get("campaign_platform"))
        lock("campaign_cta", slots.get("campaign_cta"))
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
                    label="保留已确认内容",
                    why="已确认内容不变，尚未明确的执行细节仍保留选择空间",
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
                label="Keep confirmed decisions",
                why="Preserve confirmed content; unspecified execution details remain open",
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
                "product_context": BrandQuestionContextService(self._database)
                .read(brand_id)
                .payload,
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
            journey = self._repository.get_journey(brand_id)
            runtime_result, presentation_stream = self._run_with_presentation(
                spec,
                brand_id=brand_id,
                stage="skill-stack",
                stage_revision=journey.stage_revision if journey is not None else 1,
                substep_or_slot="recommendation",
            )
            output = runtime_result.output
        except StructuredGenerationRuntimeError as error:
            raise V2PersistenceError(
                "brand_skill_recommendation_unavailable",
                "Skill recommendations are unavailable. Retry the current step.",
                stage="brand_skill_recommendation",
            ) from error
        result = skills.recommendation_stack(output)
        self._finish_presentation(
            presentation_stream,
            authoritative_id=f"brand-skill-stack:{brand_id}",
            content="\n".join(item.skill_id for item in result.entries),
        )
        return result

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
        from app.services.brand_treatment_review import BrandTreatmentReviewService

        BrandTreatmentReviewService(
            self._database,
            settings=self._settings,
            generation_runtime=self._runtime,
        ).ensure_review(brand_id, response_locale=self._workflow_response_locale(brand_id))
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
        product_context = BrandQuestionContextService(self._database).read(brand_id)
        if output is None:
            spec = StructuredGenerationSpec[CreativeTreatmentOutputV1](
                stage_name="brand_treatment_step",
                contract_name="CreativeTreatmentOutputV1",
                model_id=model_id or self._settings.llm_creative_model,
                system_prompt=_CREATIVE_TREATMENT_PROMPT,
                input_payload={
                    "product_context": product_context.payload,
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
                output_model=treatment_output_model(cast_step(journey.treatment_substep)),
                trace_metadata={"workflow_id": product_context.workflow_id},
            )
            runtime_result, presentation_stream = self._run_with_presentation(
                spec,
                brand_id=brand_id,
                stage="treatment",
                stage_revision=journey.stage_revision,
                substep_or_slot=journey.treatment_substep,
            )
            output = runtime_result.output
        else:
            presentation_stream = None
        step = output.step
        if step.step_key != journey.treatment_substep:
            raise _card_invalid("The proposal must match the current Treatment step.")
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
            state = BrandQuestionState(self._database)
            state.claim(connection, brand_id, journey.stage_revision)
            state.require_snapshot(connection, brand_id, product_context)
            self._repository.save_option_card_in_transaction(connection, brand_id, card)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="treatment",
                action="recommend",
                target_type="option_card",
                target_id=card.card_id,
                detail={"card_id": card.card_id, "context_digest": product_context.digest},
                now=now,
            )
        self._finish_presentation(
            presentation_stream,
            authoritative_id=card.card_id,
            content=step.question,
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
        state = BrandQuestionState(self._database)
        observed = self._repository.get_journey(brand_id)
        if observed is None:
            raise _not_found()
        with self._database.engine.begin() as connection:
            state.claim(connection, brand_id, observed.stage_revision)
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "treatment":
                raise _stage_mismatch()
            if not state.card_is_current(connection, brand_id, card):
                raise stale_context()
            selected = next(
                (option for option in card.options if option.option_id == option_id), None
            )
            if selected is None:
                raise _card_invalid("Selected option is not on the open card.")
            step_key = cast_step(card.target_slot_id)
            if selected.detail is not None:
                selected.detail.validate_step(step_key)
                selected_label = selected.label
                detail = selected.detail.render()
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
                detail={
                    "card_id": card_id,
                    "option_id": option_id,
                    "content_version": 2 if selected.detail is not None else 1,
                    "structured_detail": selected.detail.model_dump(mode="json")
                    if selected.detail
                    else None,
                },
                now=now,
            )
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is not None:
                self._repository.save_journey_in_transaction(
                    connection, brand_id, advance_treatment_substep(journey)
                )

    def apply_treatment_custom_candidate(
        self,
        brand_id: str,
        *,
        card_id: str,
        candidate: TreatmentCandidateV1,
    ) -> BrandOptionCardV1:
        """Append one structured Treatment candidate and select it atomically."""

        now = datetime.now(timezone.utc)
        state = BrandQuestionState(self._database)
        observed = self._repository.get_journey(brand_id)
        if observed is None or observed.stage != "treatment":
            raise _stage_mismatch()
        with self._database.engine.begin() as connection:
            state.claim(connection, brand_id, observed.stage_revision)
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "treatment":
                raise _stage_mismatch()
            if not state.card_is_current(connection, brand_id, card):
                raise stale_context()
            step_key = cast_step(card.target_slot_id)
            candidate.detail.validate_step(step_key)
            option = BrandShortOptionV1(
                option_id=candidate.option_id,
                label=candidate.label,
                why=candidate.why,
                detail=candidate.detail,
            )
            updated_card = card.model_copy(
                update={"options": self._merge_card_options(card, (option,))}
            )
            if len(updated_card.options) > 12:
                raise _card_invalid("A Brand card can contain at most twelve options.")
            self._repository.save_option_card_in_transaction(connection, brand_id, updated_card)
            self._repository.save_treatment_step_in_transaction(
                connection,
                brand_id,
                TreatmentStepResultV1(
                    step_key=step_key,
                    selected_label=option.label,
                    detail=option.detail.render(),
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
                # The Treatment document reads each step's sections from this
                # log entry, exactly like ``apply_treatment_selection``.
                detail={
                    "card_id": card_id,
                    "option_id": option.option_id,
                    "custom": True,
                    "content_version": 2,
                    "structured_detail": option.detail.model_dump(mode="json"),
                },
                now=now,
            )
            journey = self._repository.get_journey_in_transaction(connection, brand_id)
            if journey is not None:
                self._repository.save_journey_in_transaction(
                    connection, brand_id, advance_treatment_substep(journey)
                )
            return updated_card

    def append_treatment_options(
        self,
        brand_id: str,
        *,
        card_id: str,
        candidates: tuple[TreatmentCandidateV1, ...],
    ) -> BrandOptionCardV1:
        """Append structured Treatment choices and keep the current card open."""

        now = datetime.now(timezone.utc)
        state = BrandQuestionState(self._database)
        with self._database.engine.begin() as connection:
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "treatment":
                raise _stage_mismatch()
            if not state.card_is_current(connection, brand_id, card):
                raise stale_context()
            step_key = cast_step(card.target_slot_id)
            additions = tuple(
                BrandShortOptionV1(
                    option_id=item.option_id,
                    label=item.label,
                    why=item.why,
                    detail=item.detail,
                )
                for item in candidates
            )
            merged = self._merge_card_options(card, additions)
            if len(merged) > 12:
                raise _card_invalid("A Brand card can contain at most twelve options.")
            for option in merged:
                if option.detail is not None:
                    option.detail.validate_step(step_key)
            updated_card = card.model_copy(update={"options": merged})
            self._repository.save_option_card_in_transaction(connection, brand_id, updated_card)
            self._append_log(
                connection,
                brand_id=brand_id,
                stage="treatment",
                action="recommend",
                target_type="option_card",
                target_id=card_id,
                detail={"card_id": card_id, "custom": "more_options", "count": len(candidates)},
                now=now,
            )
            return updated_card

    def lock_treatment(
        self, brand_id: str, *, content_digest: str | None = None
    ) -> BrandJourneyStateV1:
        from app.services.brand_treatment_confirmation import BrandTreatmentConfirmationService

        return BrandTreatmentConfirmationService(self._database).confirm(brand_id, content_digest)

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
        entry = BrandDecisionLogEntryV1(
            log_id=f"blog_{uuid4().hex[:16]}",
            stage=stage,
            action=cast(_LogAction, action),
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            created_at=now,
        )
        self._repository.append_decision_log_in_transaction(
            connection,
            entry,
            brand_id=brand_id,
        )
        append_brand_answer_in_transaction(connection, brand_id=brand_id, entry=entry)


_MORE_OPTIONS_MARKERS = (
    "再来",
    "再给",
    "多给",
    "多来",
    "换一批",
    "换几个",
    "换个方向",
    "换一个方向",
    "其他方案",
    "其它方案",
    "别的方案",
    "更多方案",
    "更多选项",
    "还有别的",
    "还有其他",
    "还有其它",
    "重新给",
    "more options",
    "more ideas",
    "other options",
    "another",
    "different direction",
    "give me more",
)


def obvious_more_options_request(text: str) -> bool:
    """Return whether card custom text plainly asks for more alternatives."""

    normalized = text.strip().casefold()
    return any(marker in normalized for marker in _MORE_OPTIONS_MARKERS)


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
    if len(card.options) < 3 or len(card.options) > 12:
        raise _card_invalid("Brand option cards must contain between three and twelve options.")
    if stage not in {"hypothesis", "treatment"} and len(card.options) != 3:
        raise _card_invalid("This Brand card stage requires exactly three options.")


def _validate_form_cards(
    output: BrandStrategyOutputV1,
    stage: Literal["brand-memory", "campaign"],
    expected_slots: tuple[object, ...],
) -> None:
    """Validate the model's one-card-per-slot form contract before publishing."""

    cards = tuple(output.form_cards)
    by_slot = {card.target_slot_id: card for card in cards}
    expected_slot_ids = {str(slot.slot_id) for slot in expected_slots}
    if (
        len(cards) != len(expected_slots)
        or set(by_slot) != expected_slot_ids
        or any(card.stage != stage or card.target_slot_id is None for card in cards)
    ):
        raise V2PersistenceError(
            "brand_form_generation_invalid",
            "Brand foundation form did not contain one valid row for every slot.",
            stage="brand_capability_invocation",
        )
    for card in cards:
        _validate_card(card, stage)


def _validate_supplemental_options(
    output: BrandStrategyOutputV1,
    previous_options_by_slot: dict[str, tuple[BrandFormOptionV1, ...]],
    expected_slots: tuple[object, ...],
) -> None:
    """Reject a supplemental response that merely repeats prior recommendations."""

    cards_by_slot = {str(card.target_slot_id): card for card in output.form_cards}
    for slot in expected_slots:
        slot_id = str(slot.slot_id)
        previous_labels = {
            _normalized_form_option_label(option.label)
            for option in previous_options_by_slot.get(slot_id, ())
        }
        new_labels = [
            _normalized_form_option_label(option.label) for option in cards_by_slot[slot_id].options
        ]
        novel_labels = set(new_labels) - previous_labels
        if len(set(new_labels)) != len(new_labels) or len(novel_labels) < 2:
            raise ValueError(
                f"Supplemental options for {slot_id} did not contain enough new recommendations."
            )


def _normalized_form_option_label(label: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", label).split()).casefold()


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
    "For normal mode, collect one slot at a time using exactly three short options. "
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
