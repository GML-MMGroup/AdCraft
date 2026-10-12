"""Transactional conversation evidence for existing prompt dispatch transitions."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection

from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasConversationRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasNodeRow,
)
from app.schemas.agent_canvas_prompt_preparation_dispatch import PromptPreparationDispatchV1
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.v2_persistence import V2EventInsert


def append_prompt_preparation_progress(
    connection: Connection,
    events: EventRepository,
    dispatch: PromptPreparationDispatchV1,
    *,
    transition_key: str,
    created_at: datetime,
) -> None:
    """Project a committed state change without creating conversation authority."""

    conversation_id = connection.execute(
        select(AgentCanvasConversationRow.conversation_id).where(
            AgentCanvasConversationRow.workflow_id == dispatch.workflow_id
        )
    ).scalar_one_or_none()
    if conversation_id is None:
        return
    entry_id = f"entry_prompt_{sha256(transition_key.encode()).hexdigest()[:32]}"
    if (
        connection.execute(
            select(AgentCanvasChatEntryRow.entry_id).where(
                AgentCanvasChatEntryRow.entry_id == entry_id
            )
        ).scalar_one_or_none()
        is not None
    ):
        return
    node = (
        connection.execute(
            select(
                AgentCanvasNodeRow.title,
                AgentCanvasNodeRow.creative_role,
                AgentCanvasNodeRow.prompt_preparation_json,
            ).where(
                AgentCanvasNodeRow.workflow_id == dispatch.workflow_id,
                AgentCanvasNodeRow.node_id == dispatch.node_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if node is None:
        return
    preparation = json.loads(node["prompt_preparation_json"] or "{}")
    if dispatch.status == "completed" and (
        preparation.get("status") != "ready"
        or preparation.get("operation_id") != dispatch.operation_id
    ):
        return
    status = {"leased": "working", "completed": "ready"}.get(dispatch.status, dispatch.status)
    labels = {
        "waiting_user": "Prompt preparation awaits your choice",
        "queued": "Prompt preparation queued",
        "working": "Writing prompt",
        "ready": "Prompt ready; media execution is separate",
        "failed": "Prompt preparation failed",
        "superseded": "Prompt preparation superseded",
    }
    content = f"{node['title']}: {labels[status]}."
    if status == "failed" and dispatch.last_error_code:
        content += f" Error: {dispatch.last_error_code}."
    sequence_no = 1 + int(
        connection.execute(
            select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                AgentCanvasChatEntryRow.conversation_id == conversation_id
            )
        ).scalar_one()
    )
    locale = connection.execute(
        select(AgentCanvasGuidanceSessionRow.response_locale).where(
            AgentCanvasGuidanceSessionRow.workflow_id == dispatch.workflow_id
        )
    ).scalar_one_or_none()
    metadata = {
        "type": "prompt_preparation",
        "node_id": dispatch.node_id,
        "node_title": node["title"],
        "capability_id": _progress_capability(str(node["creative_role"])),
        "dispatch_id": dispatch.dispatch_id,
        "operation_id": dispatch.operation_id,
        "status": status,
        "attempt": dispatch.attempt_no,
        "error_code": dispatch.last_error_code,
        "response_locale": str(locale or "und"),
        "presentation_key": f"planning:prompt:{dispatch.dispatch_id}",
        "presentation_revision": sequence_no,
    }
    connection.execute(
        insert(AgentCanvasChatEntryRow).values(
            entry_id=entry_id,
            conversation_id=conversation_id,
            workflow_id=dispatch.workflow_id,
            sequence_no=sequence_no,
            entry_type="planning_progress",
            speaker="adcraft_video_agent",
            content=content,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            created_at=created_at.isoformat(),
        )
    )
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=dispatch.workflow_id,
            node_id=dispatch.node_id,
            conversation_id=conversation_id,
            event_type="chat_message_created",
            transition_key=f"{transition_key}:chat-progress",
            created_at=created_at.isoformat(),
            payload={
                "message_id": entry_id,
                "speaker": "adcraft_video_agent",
                "refresh": ["timeline"],
            },
        ),
    )


def _progress_capability(creative_role: str) -> CapabilityIdV1:
    """Associate progress with an existing stage without changing execution ownership."""

    capabilities: dict[str, CapabilityIdV1] = {
        "world_setting": "world_setting",
        "product": "product_design",
        "prop": "prop_design",
        "character": "character_design",
        "scene": "scene_design",
        "script": "script_authoring",
        "storyboard_sequence": "storyboard_design",
        "storyboard_video": "video_direction",
        "bgm": "bgm_direction",
    }
    return capabilities.get(creative_role, "quick_media")
