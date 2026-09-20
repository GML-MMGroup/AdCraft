"""Brand Skill catalog adaptation, strict selection, and existing style activation."""

from __future__ import annotations

from sqlalchemy.engine import Connection
from sqlalchemy import update

from app.persistence.agent_canvas_conversation_repository import AgentCanvasConversationRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository
from app.persistence.models import AgentCanvasGuidanceSessionRow
from app.schemas.agent_canvas_conversation import VideoSkillRunCreateRequestV2
from app.schemas.brand_professional_mode import (
    BrandCreativeMethodCatalogV1,
    BrandCreativeMethodV1,
    BrandSkillRecommendationsV1,
    BrandSkillReferenceV1,
    SkillStackEntryV1,
    SkillStackV1,
)
from app.services.agent_canvas_style_activation import StyleSkillActivationService
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.services.agent_canvas_video_skills import VideoSkillRegistry


class BrandSkillStackService:
    def __init__(self, database: V2Database) -> None:
        self._database = database
        self._repository = BrandDecisionRepository(database)
        self._styles = VideoSkillRegistry()

    def creative_method_catalog(self) -> BrandCreativeMethodCatalogV1:
        return BrandCreativeMethodCatalogV1(
            items=tuple(
                BrandCreativeMethodV1.model_validate(row)
                for row in self._repository.list_creative_skills()
                if row["skill_kind"] == "creative_method"
            )
        )

    def recommendation_catalogs(self) -> dict[str, object]:
        return {
            "creative_methods": self.creative_method_catalog().model_dump(mode="json")["items"],
            "audiovisual_styles": [
                item.model_dump(mode="json")
                for item in self._styles.load_catalog().items
                if item.skill_id != "platform-default"
            ],
        }

    def treatment_context(self, brand_id: str, substep: str | None) -> dict[str, object]:
        stack = self._repository.get_skill_stack(brand_id)
        if stack is None:
            return {}
        selected = tuple(entry for entry in stack.entries if entry.selected)
        context: dict[str, object] = {
            "skill_stack": SkillStackV1(entries=selected).model_dump(mode="json")
        }
        workflow_id = self._repository.workflow_id_for_brand(brand_id)
        if workflow_id is None or not any(entry.version for entry in selected):
            return context
        snapshot = AgentCanvasConversationRepository(
            self._database, EventRepository(self._database)
        ).get_active_creative_direction_snapshot(workflow_id)
        role = {
            "character": "character",
            "scene": "scene",
            "visual": "storyboard",
            "camera": "video",
            "editing": "video",
            "sound": "bgm",
        }.get(substep, "script")
        context["style_guidance"] = (
            CreativeDirectionService().resolve_style_context(snapshot, role).model_dump(mode="json")
        )
        chosen = {
            (entry.skill_id, entry.version)
            for entry in selected
            if entry.skill_kind == "creative_method"
        }
        context["creative_methods"] = [
            item.model_dump(mode="json")
            for item in self.creative_method_catalog().items
            if (item.skill_id, item.version) in chosen
        ]
        return context

    def recommendation_stack(self, output: BrandSkillRecommendationsV1) -> SkillStackV1:
        methods = self._method_entries(output.creative_methods)
        styles = self._style_entries(output.audiovisual_styles)
        return SkillStackV1(
            entries=tuple(
                entry.model_copy(
                    update={
                        "reason": choice.reason,
                        "selected": index == 0 if entry.skill_kind == "audiovisual_style" else True,
                    }
                )
                for entries, choices in (
                    (methods, output.creative_methods),
                    (styles, output.audiovisual_styles),
                )
                for index, (entry, choice) in enumerate(zip(entries, choices))
            )
        )

    def selection_stack(
        self,
        methods: tuple[BrandSkillReferenceV1, ...],
        style: BrandSkillReferenceV1,
        previous: SkillStackV1 | None,
    ) -> SkillStackV1:
        selected = (*self._method_entries(methods), *self._style_entries((style,)))
        by_key = {(entry.skill_kind, entry.skill_id): entry for entry in selected}
        entries = []
        for entry in previous.entries if previous else ():
            replacement = by_key.pop((entry.skill_kind, entry.skill_id), None)
            entries.append(
                replacement.model_copy(
                    update={
                        "reason": entry.reason if replacement.version == entry.version else None
                    }
                )
                if replacement
                else entry.model_copy(update={"selected": False})
            )
        return SkillStackV1(entries=tuple((*entries, *by_key.values())))

    def activate(
        self, connection: Connection, brand_id: str, stack: SkillStackV1, card_id: str
    ) -> None:
        selected = [entry for entry in stack.entries if entry.selected]
        styles = [entry for entry in selected if entry.skill_kind == "audiovisual_style"]
        methods = [entry for entry in selected if entry.skill_kind == "creative_method"]
        if len(styles) != 1 or not methods or any(entry.version is None for entry in selected):
            raise _invalid("Select one style and at least one versioned creative method.")
        self._method_entries(
            tuple(BrandSkillReferenceV1(skill_id=e.skill_id, version=e.version) for e in methods)
        )
        style = styles[0]
        workflow_id = self._repository.workflow_id_for_brand(brand_id)
        if workflow_id is None:
            raise _invalid("The brand must belong to an existing workflow.")
        events = EventRepository(self._database)
        conversations = AgentCanvasConversationRepository(self._database, events)
        workflows = AgentCanvasWorkflowRepository(
            self._database, ProjectRepository(self._database), events
        )
        run = StyleSkillActivationService(workflows, conversations, self._styles).activate(
            workflow_id,
            VideoSkillRunCreateRequestV2(skill_id=style.skill_id, skill_version=style.version),
            idempotency_key=f"brand-stack:{brand_id}:{card_id}",
            connection=connection,
        )
        connection.execute(
            update(AgentCanvasGuidanceSessionRow)
            .where(
                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id,
            )
            .values(
                active_style_skill_run_id=run.skill_run_id,
                revision=AgentCanvasGuidanceSessionRow.revision + 1,
            )
        )

    def _method_entries(
        self, choices: tuple[BrandSkillReferenceV1, ...]
    ) -> tuple[SkillStackEntryV1, ...]:
        _distinct(choices)
        catalog = {
            (item.skill_id, item.version): item for item in self.creative_method_catalog().items
        }
        entries = []
        for choice in choices:
            item = catalog.get((choice.skill_id, choice.version))
            if item is None:
                raise _invalid("Creative method id or version is not in the catalog.")
            entries.append(
                SkillStackEntryV1(
                    skill_kind="creative_method",
                    skill_id=item.skill_id,
                    title=item.title,
                    version=item.version,
                )
            )
        return tuple(entries)

    def _style_entries(
        self, choices: tuple[BrandSkillReferenceV1, ...]
    ) -> tuple[SkillStackEntryV1, ...]:
        _distinct(choices)
        catalog = {
            (item.skill_id, item.version): item for item in self._styles.load_catalog().items
        }
        entries = []
        for choice in choices:
            item = catalog.get((choice.skill_id, choice.version))
            if item is None:
                raise _invalid("Audiovisual style id or version is not in the public catalog.")
            entries.append(
                SkillStackEntryV1(
                    skill_kind="audiovisual_style",
                    skill_id=item.skill_id,
                    title=item.title,
                    version=item.version,
                )
            )
        return tuple(entries)


def _distinct(choices: tuple[BrandSkillReferenceV1, ...]) -> None:
    if len({item.skill_id for item in choices}) != len(choices):
        raise _invalid("Each selected Skill must have a distinct id.")


def _invalid(message: str) -> V2PersistenceError:
    return V2PersistenceError("brand_skill_selection_invalid", message, stage="brand_skill_stack")
