"""Resolve consultation facts through the canonical public catalog only."""

from __future__ import annotations

from app.persistence.agent_canvas_conversation_repository import AgentCanvasConversationRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.style_skill_consultation import (
    StyleSkillConsultationContextV1,
    StyleSkillConsultationQueryV1,
    StyleSkillPublicFactV1,
    catalog_fact_bytes,
)
from app.services.agent_canvas_video_skills import VideoSkillRegistry


class StyleSkillConsultationResolver:
    def __init__(
        self, registry: VideoSkillRegistry, conversations: AgentCanvasConversationRepository
    ) -> None:
        self._registry = registry
        self._conversations = conversations

    def resolve(
        self, workflow_id: str, query: StyleSkillConsultationQueryV1
    ) -> StyleSkillConsultationContextV1:
        catalog = self._registry.load_catalog()
        try:
            selected = self._conversations.get_active_style_skill_run(workflow_id)
        except V2PersistenceError as error:
            if error.code != "style_skill_run_not_found":
                raise
            selected = None
        selected_id = selected.skill_id if selected else None
        selected_version = selected.skill_version if selected else None
        facts = {
            item.skill_id: StyleSkillPublicFactV1.model_validate(
                item.model_dump(
                    exclude={"preview", "display_order"},
                )
            )
            for item in catalog.items
        }
        priority_ids = tuple(
            dict.fromkeys(
                (
                    *((selected_id,) if selected_id else ()),
                    *query.skill_ids,
                )
            )
        )
        unavailable = tuple(
            skill_id
            for skill_id in priority_ids
            if skill_id not in facts
            or (skill_id == selected_id and facts[skill_id].version != selected_version)
        )
        entries: tuple[StyleSkillPublicFactV1, ...] = ()
        for skill_id in dict.fromkeys((*priority_ids, *facts)):
            if skill_id in unavailable:
                continue
            candidate = (*entries, facts[skill_id])
            if len(candidate) > 24 or len(catalog_fact_bytes(candidate)) > 16_384:
                if skill_id in priority_ids:
                    raise V2PersistenceError(
                        "video_skill_catalog_invalid",
                        "Focused public Style Skill facts exceed the consultation budget.",
                        stage="style_skill_consultation",
                    )
                continue
            entries = candidate
        session = self._conversations.get_guidance_session_or_none(workflow_id)
        return StyleSkillConsultationContextV1(
            catalog_version=catalog.catalog_version,
            selected_skill_id=selected_id,
            selected_skill_version=selected_version,
            query=query,
            entries=entries,
            omitted_entry_count=len(catalog.items) - len(entries),
            unavailable_skill_ids=unavailable,
            requirement_summary=session.goal.summary if session else "",
        )
