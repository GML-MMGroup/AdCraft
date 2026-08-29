"""Persist the user-facing projection of an accepted guided questionnaire."""

from __future__ import annotations

import json

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection

from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasConversationRow,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidedCustomAnswerV1,
    GuidedQuestionAnswerV1,
    GuidedQuestionnaireSubmitV1,
    GuidedQuestionnaireV1,
    GuidedSkipAnswerV1,
)


PRESENTATION_KIND = "guided_answer"
PRESENTATION_SCHEMA_VERSION = 1


def append_guided_answer_message_in_transaction(
    connection: Connection,
    *,
    workflow_id: str,
    interaction_id: str,
    submission_id: str,
    questionnaire: GuidedQuestionnaireV1,
    request: GuidedQuestionnaireSubmitV1,
    created_at: str,
) -> None:
    """Append one deterministic user message for an accepted questionnaire."""

    answer_by_id = {answer.question_id: answer for answer in request.answers}
    answers: list[dict[str, str]] = []
    for question in questionnaire.questions:
        answer = answer_by_id.get(question.question_id)
        if answer is None:
            continue
        if isinstance(answer, GuidedQuestionAnswerV1):
            option = next(
                option for option in question.options if option.option_id == answer.option_id
            )
            value = option.title
        elif isinstance(answer, GuidedCustomAnswerV1):
            value = answer.value
        elif isinstance(answer, GuidedSkipAnswerV1):
            value = "Skipped"
        else:
            raise AssertionError("Guided questionnaire answer union is exhaustive.")
        answers.append(
            {
                "question_id": question.question_id,
                "label": question.prompt,
                "value": value,
            }
        )

    conversation_id = connection.execute(
        select(AgentCanvasConversationRow.conversation_id).where(
            AgentCanvasConversationRow.workflow_id == workflow_id
        )
    ).scalar_one()
    metadata: dict[str, object] = {
        "presentation_kind": PRESENTATION_KIND,
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "submission_id": submission_id,
        "interaction_id": interaction_id,
        "answers": answers,
    }
    content = "\n".join(f"{answer['label']}: {answer['value']}" for answer in answers)
    sequence_no = (
        int(
            connection.execute(
                select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                    AgentCanvasChatEntryRow.conversation_id == conversation_id
                )
            ).scalar_one()
        )
        + 1
    )
    connection.execute(
        insert(AgentCanvasChatEntryRow).values(
            entry_id=f"guided_answer_{submission_id}",
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            sequence_no=sequence_no,
            entry_type="message",
            speaker="user",
            content=content,
            metadata_json=json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
            created_at=created_at,
        )
    )
