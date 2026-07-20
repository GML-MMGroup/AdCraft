from __future__ import annotations

from time import perf_counter
from typing import Any

from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
)
from app.services.agent_trace import AgentTraceWriter, utc_now
from app.services.conversation_memory import ConversationMemoryRepair


class AgentConversationTraceMixin:
    def _trace_events(
        self,
        conversation: AgentConversation,
        events: list[AgentConversationEvent],
        asset_references: list[Any],
    ) -> None:
        workflow_id = conversation.workflow_id
        if not workflow_id:
            return
        referenced_asset_ids = [
            str(reference.asset_id)
            for reference in asset_references
            if getattr(reference, "asset_id", None)
        ]
        writer = AgentTraceWriter(self._settings.media_data_dir, workflow_id)
        for event in events:
            started_at = utc_now()
            started_counter = perf_counter()
            writer.append(
                agent=event.speaker_agent or "agent_conversation",
                model=None,
                prompt=event.text,
                output=event.model_dump(mode="json"),
                error=event.metadata.get("error"),
                started_at=started_at,
                finished_at=utc_now(),
                duration_ms=round((perf_counter() - started_counter) * 1000),
                metadata={
                    "trace_role": "agent_conversation",
                    "conversation_id": conversation.conversation_id,
                    "event_id": event.event_id,
                    "speaker_agent": event.speaker_agent,
                    "target_agent": event.target_agent,
                    "target_node_id": event.target_node_id,
                    "action_type": event.metadata.get("action_type"),
                    "referenced_asset_ids": referenced_asset_ids,
                },
            )

    def _trace_memory_warning(
        self,
        conversation: AgentConversation,
        repair: ConversationMemoryRepair,
    ) -> None:
        workflow_id = conversation.workflow_id
        if not workflow_id:
            return
        started_at = utc_now()
        started_counter = perf_counter()
        AgentTraceWriter(self._settings.media_data_dir, workflow_id).append(
            agent="creative_director",
            model=None,
            prompt="conversation memory repair",
            output={
                "conversation_id": conversation.conversation_id,
                "warning_code": repair.warning_code,
                "message": repair.message,
                "target": repair.target,
            },
            error=None,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=round((perf_counter() - started_counter) * 1000),
            metadata={
                "trace_role": "agent_conversation",
                "conversation_id": conversation.conversation_id,
                "warning_code": repair.warning_code,
                "memory_target": repair.target,
            },
        )
