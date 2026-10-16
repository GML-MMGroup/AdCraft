"""Durable chat projections of accepted Brand decisions, without running the Agent."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping
import json

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection

from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasConversationRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasWorkflowRow,
    BrandOptionCardRow,
    BrandRow,
)
from app.schemas.brand_professional_mode import BrandDecisionLogEntryV1


def append_brand_answer_in_transaction(
    connection: Connection, *, brand_id: str, entry: BrandDecisionLogEntryV1
) -> bool:
    """Project only recorded choices with a matching published question.

    Called in the decision transaction; historical repair uses the same projector.
    Stable interaction identity makes repeated repair safe without rewriting cursors.
    """
    if (entry.action, entry.target_type) not in {
        ("select", "option"),
        ("select", "hypothesis"),
        ("select", "treatment_step"),
        ("confirm", "adspec"),
        ("edit", "adspec"),
        ("confirm", "skill_stack"),
    }:
        return False
    conversations = (
        connection.execute(
            select(
                AgentCanvasConversationRow.conversation_id, AgentCanvasConversationRow.workflow_id
            )
            .join(
                AgentCanvasWorkflowRow,
                AgentCanvasWorkflowRow.workflow_id == AgentCanvasConversationRow.workflow_id,
            )
            .join(BrandRow, BrandRow.project_id == AgentCanvasWorkflowRow.project_id)
            .where(BrandRow.brand_id == brand_id)
        )
        .mappings()
        .all()
    )
    if len(conversations) != 1:
        return False
    conversation = conversations[0]
    card_id = entry.detail.get("card_id")
    if entry.target_type == "skill_stack":
        card_id = entry.target_id
    option_id = (
        entry.detail.get("option_id") if entry.target_type == "treatment_step" else entry.target_id
    )
    interactions = (
        connection.execute(
            select(AgentCanvasGuidedInteractionRow).where(
                AgentCanvasGuidedInteractionRow.workflow_id == conversation["workflow_id"],
                AgentCanvasGuidedInteractionRow.created_at <= entry.created_at.isoformat(),
            )
        )
        .mappings()
        .all()
    )
    matches = []
    for interaction in interactions:
        content = json.loads(interaction["content_json"])
        if content.get("capability_id") != f"brand_{entry.stage}":
            continue
        if card_id:
            if content.get("action_id") != card_id:
                continue
        elif entry.target_type != "hypothesis" or not any(
            option["option_id"] == option_id for option in content.get("options", [])
        ):
            continue
        matches.append((interaction, content))
    if len(matches) != 1:
        return False
    interaction, content = matches[0]
    raw_card = connection.execute(
        select(BrandOptionCardRow.payload_json).where(
            BrandOptionCardRow.brand_id == brand_id,
            BrandOptionCardRow.card_id == content["action_id"],
        )
    ).scalar_one_or_none()
    if raw_card is not None:
        card = json.loads(raw_card)
    elif entry.target_type == "hypothesis":
        # Hypothesis cards are persisted only as guided interactions.
        card = {
            "card_id": content["action_id"],
            "question": interaction["title"],
            "options": [
                {"option_id": o["option_id"], "label": o["title"]} for o in content["options"]
            ],
        }
    else:
        return False
    option = next((o for o in card["options"] if o["option_id"] == option_id), None)
    value = _answer_value(entry, option)
    if not value:
        return False
    return _append(connection, conversation, entry, interaction["interaction_id"], card, value)


def _answer_value(entry: BrandDecisionLogEntryV1, option: dict[str, Any] | None) -> str | None:
    if entry.target_type == "skill_stack":
        titles = [item["title"] for item in entry.detail.get("entries", []) if item.get("selected")]
        return " / ".join(titles) or None
    if entry.target_type == "option" and entry.target_id in {"custom", "delegate"}:
        if entry.target_id == "delegate":
            return "Delegated"
        value = entry.detail.get("value")
        return value if isinstance(value, str) and value.strip() else None
    return option["label"] if option else None


def _append(
    connection: Connection,
    conversation: Mapping[str, Any],
    entry: BrandDecisionLogEntryV1,
    interaction_id: str,
    card: dict[str, Any],
    value: str,
) -> bool:
    submission_id = "brand_" + sha256(interaction_id.encode()).hexdigest()[:32]
    entry_id = f"guided_answer_{submission_id}"
    existing = (
        connection.execute(
            select(AgentCanvasChatEntryRow.entry_id, AgentCanvasChatEntryRow.metadata_json).where(
                AgentCanvasChatEntryRow.conversation_id == conversation["conversation_id"]
            )
        )
        .mappings()
        .all()
    )
    if any(
        item["entry_id"] == entry_id
        or (
            (metadata := json.loads(item["metadata_json"])).get("presentation_kind")
            == "guided_answer"
            and metadata.get("interaction_id") == interaction_id
        )
        for item in existing
    ):
        return False
    metadata = {
        "presentation_kind": "guided_answer",
        "schema_version": 1,
        "submission_id": submission_id,
        "interaction_id": interaction_id,
        "brand_decision_log_id": entry.log_id,
        "answers": [{"question_id": card["card_id"], "label": card["question"], "value": value}],
    }
    sequence = (
        connection.execute(
            select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                AgentCanvasChatEntryRow.conversation_id == conversation["conversation_id"]
            )
        ).scalar_one()
        + 1
    )
    connection.execute(
        insert(AgentCanvasChatEntryRow).values(
            entry_id=entry_id,
            conversation_id=conversation["conversation_id"],
            workflow_id=conversation["workflow_id"],
            sequence_no=sequence,
            entry_type="message",
            speaker="user",
            content=f"{card['question']}: {value}",
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            created_at=entry.created_at.isoformat(),
        )
    )
    return True
