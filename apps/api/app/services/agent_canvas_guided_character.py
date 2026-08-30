"""Deterministic authority for unresolved Character cast decisions."""

from __future__ import annotations

from dataclasses import dataclass
import re

from pydantic import TypeAdapter, ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_guided_interactions import (
    GuidedChoiceOptionV1,
    GuidedCustomAnswerV1,
    GuidedQuestionAnswerV1,
    GuidedQuestionnaireSubmitV1,
    GuidedQuestionnaireV1,
    GuidedQuestionV1,
    GuidedSkipAnswerV1,
)
from app.schemas.agent_canvas_requirements import (
    CharacterCountValueV1,
    RequirementLedgerRevisionV1,
)
from app.services.agent_canvas_requirements import character_occurrence_authority_for_authoring
from app.schemas.language import canonicalize_bcp47_tag


CHARACTER_COUNT_QUESTION_ID = "character_count"
CHARACTER_COUNT_OPTIONS: tuple[tuple[str, int], ...] = (
    ("character_count_0", 0),
    ("character_count_1", 1),
    ("character_count_2", 2),
    ("character_count_3", 3),
)
_CHARACTER_COUNT_VALUES = dict(CHARACTER_COUNT_OPTIONS)
_CHARACTER_COUNT_ADAPTER = TypeAdapter(CharacterCountValueV1)
_INTEGER_PATTERN = re.compile(r"^[0-9]+$")


@dataclass(frozen=True, slots=True)
class ResolvedCharacterAnswer:
    """Canonical count and bounded source lineage from one typed answer."""

    count: int
    source_text: str
    source_option_id: str | None


class GuidedCharacterAuthorityPolicy:
    """Build and resolve the Character count question without model calls."""

    def questionnaire(
        self,
        requirements: RequirementLedgerRevisionV1,
        *,
        response_locale: str,
    ) -> GuidedQuestionnaireV1 | None:
        # Locale is validated by the central policy; authority IDs and values are
        # deliberately independent of the resulting presentation locale.
        canonicalize_bcp47_tag(response_locale)
        authority = character_occurrence_authority_for_authoring(requirements)
        if authority.status != "unresolved":
            return None
        return GuidedQuestionnaireV1(
            questions=(
                GuidedQuestionV1(
                    question_id=CHARACTER_COUNT_QUESTION_ID,
                    prompt="How many characters should appear in the advertisement?",
                    options=tuple(
                        GuidedChoiceOptionV1(
                            option_id=option_id,
                            title=f"{count} characters",
                            summary=(
                                "Use no characters."
                                if count == 0
                                else f"Author {count} character{'s' if count != 1 else ''}."
                            ),
                            recommended=False,
                        )
                        for option_id, count in CHARACTER_COUNT_OPTIONS
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
    ) -> ResolvedCharacterAnswer:
        if (
            len(questionnaire.questions) != 1
            or questionnaire.questions[0].question_id != CHARACTER_COUNT_QUESTION_ID
            or len(request.answers) != 1
            or request.answers[0].question_id != CHARACTER_COUNT_QUESTION_ID
        ):
            raise _error(
                "guided_interaction_incomplete",
                "The Character count questionnaire requires exactly one current answer.",
            )
        question = questionnaire.questions[0]
        answer = request.answers[0]
        source_option_id: str | None = None
        if isinstance(answer, GuidedQuestionAnswerV1):
            if answer.option_id not in _CHARACTER_COUNT_VALUES or not any(
                option.option_id == answer.option_id for option in question.options
            ):
                raise _error(
                    "guided_interaction_option_invalid",
                    "The Character count answer is not a current option.",
                )
            count = _CHARACTER_COUNT_VALUES[answer.option_id]
            source_text = next(
                option.title for option in question.options if option.option_id == answer.option_id
            )
            source_option_id = answer.option_id
        elif isinstance(answer, GuidedCustomAnswerV1):
            if not question.allow_custom:
                raise _error(
                    "guided_interaction_action_not_allowed",
                    "This question does not accept a custom answer.",
                )
            source_text = answer.value
            raw = answer.value.strip()
            if not _INTEGER_PATTERN.fullmatch(raw):
                raise _character_count_error()
            try:
                count = _CHARACTER_COUNT_ADAPTER.validate_python(int(raw))
            except (ValidationError, ValueError, TypeError, OverflowError) as error:
                raise _character_count_error() from error
        elif isinstance(answer, GuidedSkipAnswerV1):
            raise _error(
                "guided_interaction_action_not_allowed",
                "This question cannot be skipped.",
            )
        else:
            raise _character_count_error()
        return ResolvedCharacterAnswer(
            count=count,
            source_text=source_text,
            source_option_id=source_option_id,
        )


def _character_count_error() -> V2PersistenceError:
    return _error(
        "character_count_answer_invalid",
        "Character count must be an integer from 0 through 32.",
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_character_authority")
