"""Deterministic authority for guided production duration."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from pydantic import TypeAdapter, ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_decision_bundles import SetDurationSecondsDecisionEffectV1
from app.schemas.agent_canvas_guided_interactions import (
    GuidedChoiceOptionV1,
    GuidedCustomAnswerV1,
    GuidedQuestionAnswerV1,
    GuidedQuestionnaireSubmitV1,
    GuidedQuestionnaireV1,
    GuidedQuestionV1,
)
from app.schemas.agent_canvas_requirements import (
    DurationSecondsValueV1,
    RequirementLedgerRevisionV1,
)
from app.schemas.agent_canvas_production_journey import JourneyStageV2
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthorityPlanV2,
)
from app.schemas.agent_working_documents import (
    StoryboardProductionPlanContentV2,
    StoryboardProductionPlanContentV3,
)
from app.services.agent_canvas_storyboard_sequence_windows import (
    StoryboardSequenceWindowPlanner,
)


DURATION_QUESTION_ID = "production_duration_seconds"
DURATION_OPTIONS: tuple[tuple[str, int], ...] = (
    ("duration_seconds_15", 15),
    ("duration_seconds_30", 30),
    ("duration_seconds_45", 45),
    ("duration_seconds_60", 60),
)

_DURATION_ADAPTER = TypeAdapter(DurationSecondsValueV1)
_OPTION_VALUES = dict(DURATION_OPTIONS)
_TIME_DEPENDENT_STAGES: frozenset[JourneyStageV2] = frozenset(
    {
        "narrative_direction",
        "style_lock",
        "storyboard_plan",
        "storyboard_grids",
        "videos",
        "bgm",
        "editing",
    }
)


@dataclass(frozen=True, slots=True)
class ResolvedDurationAnswer:
    effect: SetDurationSecondsDecisionEffectV1
    source_text: str
    source_option_id: str | None


class GuidedDurationAuthorityPolicy:
    """Project one required question and resolve its answers without an Agent."""

    def questionnaire(
        self,
        requirements: RequirementLedgerRevisionV1,
        *,
        response_locale: str,
    ) -> GuidedQuestionnaireV1 | None:
        del response_locale
        if self.duration_or_none(requirements) is not None:
            return None
        return GuidedQuestionnaireV1(
            questions=(
                GuidedQuestionV1(
                    question_id=DURATION_QUESTION_ID,
                    prompt="Choose the total advertisement duration.",
                    options=tuple(
                        GuidedChoiceOptionV1(
                            option_id=option_id,
                            title=f"{seconds} seconds",
                            summary=f"Produce a {seconds}-second advertisement.",
                            recommended=seconds == 30,
                        )
                        for option_id, seconds in DURATION_OPTIONS
                    ),
                    allow_custom=True,
                    allow_skip=False,
                    required=True,
                ),
            )
        )

    def resolve_answer(
        self,
        questionnaire: GuidedQuestionnaireV1,
        request: GuidedQuestionnaireSubmitV1,
    ) -> ResolvedDurationAnswer:
        if (
            len(questionnaire.questions) != 1
            or questionnaire.questions[0].question_id != DURATION_QUESTION_ID
            or len(request.answers) != 1
            or request.answers[0].question_id != DURATION_QUESTION_ID
        ):
            raise _error(
                "guided_interaction_incomplete",
                "The duration questionnaire requires exactly one current answer.",
            )
        question = questionnaire.questions[0]
        answer = request.answers[0]
        source_option_id: str | None = None
        if isinstance(answer, GuidedQuestionAnswerV1):
            if answer.option_id not in _OPTION_VALUES or not any(
                option.option_id == answer.option_id for option in question.options
            ):
                raise _error(
                    "guided_interaction_option_invalid",
                    "The duration answer is not a current option.",
                )
            value: object = _OPTION_VALUES[answer.option_id]
            source_text = next(
                option.title for option in question.options if option.option_id == answer.option_id
            )
            source_option_id = answer.option_id
        elif isinstance(answer, GuidedCustomAnswerV1):
            source_text = answer.value
            try:
                value = float(answer.value.strip())
            except ValueError as error:
                raise _duration_error() from error
            if not isfinite(value):
                raise _duration_error()
        else:
            raise _duration_error()
        try:
            duration = _DURATION_ADAPTER.validate_python(value)
            StoryboardSequenceWindowPlanner.plan(
                total_duration_seconds=duration,
                aspect_ratio="16:9",
            )
        except (ValidationError, V2PersistenceError, ValueError) as error:
            raise _duration_error() from error
        return ResolvedDurationAnswer(
            effect=SetDurationSecondsDecisionEffectV1(
                control="duration_seconds",
                value=duration,
            ),
            source_text=source_text,
            source_option_id=source_option_id,
        )

    def require_duration(self, requirements: RequirementLedgerRevisionV1) -> float:
        duration = self.duration_or_none(requirements)
        if duration is None:
            raise _error(
                "production_duration_required",
                "Production duration must be confirmed before time-dependent authoring.",
            )
        return duration

    def require_for_stage(
        self,
        requirements: RequirementLedgerRevisionV1,
        stage: JourneyStageV2,
    ) -> float | None:
        if stage not in _TIME_DEPENDENT_STAGES:
            return self.duration_or_none(requirements)
        return self.require_duration(requirements)

    def plan_sequences(
        self,
        requirements: RequirementLedgerRevisionV1,
        *,
        aspect_ratio: object,
        explicit_sequence_count: object = None,
    ) -> StoryboardSequenceAuthorityPlanV2:
        return StoryboardSequenceWindowPlanner.plan(
            total_duration_seconds=self.require_duration(requirements),
            aspect_ratio=aspect_ratio,
            explicit_sequence_count=explicit_sequence_count,
        )

    def validate_plan(
        self,
        requirements: RequirementLedgerRevisionV1,
        plan: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
    ) -> float:
        duration = self.require_duration(requirements)
        try:
            expected = StoryboardSequenceWindowPlanner.plan(
                total_duration_seconds=duration,
                aspect_ratio=plan.global_parameters.aspect_ratio,
                explicit_sequence_count=plan.global_parameters.segment_count,
            )
        except V2PersistenceError as error:
            raise _duration_contract_error() from error
        actual_windows = tuple(
            (segment.order, segment.start_seconds, segment.end_seconds) for segment in plan.segments
        )
        expected_windows = tuple(
            (window.order, window.start_seconds, window.end_seconds) for window in expected.windows
        )
        if (
            plan.global_parameters.total_duration_seconds != duration
            or len(plan.segments) != plan.global_parameters.segment_count
            or actual_windows != expected_windows
        ):
            raise _duration_contract_error()
        return duration

    @staticmethod
    def duration_or_none(requirements: RequirementLedgerRevisionV1) -> float | None:
        return next(
            (
                float(control.value)
                for control in requirements.ledger.hard_controls
                if control.control == "duration_seconds"
            ),
            None,
        )


def _duration_error() -> V2PersistenceError:
    return _error(
        "guided_duration_value_invalid",
        "Custom duration must be a valid numeric seconds value.",
    )


def _duration_contract_error() -> V2PersistenceError:
    return _error(
        "production_duration_contract_invalid",
        "Storyboard Production Plan timing conflicts with canonical duration.",
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_duration_authority")
