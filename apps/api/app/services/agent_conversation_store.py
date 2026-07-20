from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationCreateRequest,
)
from app.services.agent_trace import utc_now

from app.services.agent_conversation_common import (
    AgentConversationInputError,
)


class AgentConversationStoreMixin:
    @property
    def _conversation_dir(self) -> Path:
        return self._settings.media_data_dir / "agent_conversations"

    def create(self, request: AgentConversationCreateRequest) -> AgentConversation:
        now = utc_now().isoformat()
        conversation = AgentConversation(
            conversation_id=f"conv_{uuid4().hex[:12]}",
            workflow_id=request.workflow_id,
            focus_node_id=request.focus_node_id,
            topic=request.topic,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self._conversation_memory.ensure_memory(conversation)
        self._save(conversation)
        return conversation

    def list(
        self,
        *,
        workflow_id: str | None = None,
        focus_node_id: str | None = None,
        status: str | None = None,
    ) -> list[AgentConversation]:
        conversations = [self._load_from_path(path) for path in self._conversation_paths()]
        if workflow_id is not None:
            conversations = [
                conversation
                for conversation in conversations
                if conversation.workflow_id == workflow_id
            ]
        if focus_node_id is not None:
            conversations = [
                conversation
                for conversation in conversations
                if conversation.focus_node_id == focus_node_id
            ]
        if status is not None:
            conversations = [
                conversation for conversation in conversations if conversation.status == status
            ]
        return sorted(conversations, key=lambda item: item.updated_at, reverse=True)

    def get(self, conversation_id: str) -> AgentConversation:
        return self._load(conversation_id)

    def _conversation_paths(self) -> list[Path]:
        if not self._conversation_dir.exists():
            return []
        return sorted(self._conversation_dir.glob("conv_*.json"))

    def _path(self, conversation_id: str) -> Path:
        if (
            not conversation_id
            or "/" in conversation_id
            or "\\" in conversation_id
            or Path(conversation_id).name != conversation_id
        ):
            raise AgentConversationInputError(f"invalid conversation_id: {conversation_id}")
        return self._conversation_dir / f"{conversation_id}.json"

    def _load(self, conversation_id: str) -> AgentConversation:
        path = self._path(conversation_id)
        if not path.exists():
            raise AgentConversationInputError(f"unknown conversation_id: {conversation_id}")
        return self._load_from_path(path)

    def _load_from_path(self, path: Path) -> AgentConversation:
        return AgentConversation.model_validate_json(path.read_text(encoding="utf-8"))

    def _save(self, conversation: AgentConversation) -> None:
        self._conversation_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(conversation.conversation_id)
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(conversation.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
