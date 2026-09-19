"""Brand Treatment lock handoff into the existing intent-planning path.

On the treatment-lock receipt this service maps locked Campaign and AdSpec
decisions into a WorkflowV2PlanFromPromptRequest and invokes the existing
WorkflowV2Service.plan_from_prompt. Locked constraints travel as explicit
request context so the existing intent planner owns validation.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text as sql_text

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas_requirements import (
    AspectRatioControlPatchV1,
    AudioModeControlPatchV1,
    DurationSecondsControlPatchV1,
    ProductCountControlPatchV1,
    RequirementElementPresencePatchV1,
    RequirementDirectivePatchV1,
    RequirementPatchV1,
    StoryboardSequenceCountControlPatchV1,
    VideoSegmentCountControlPatchV1,
)
from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.services.agent_canvas_requirements import AgentCanvasRequirementService
from app.services.workflow_v2 import WorkflowV2Service


@dataclass(frozen=True)
class BrandHandoffResult:
    workflow_id: str | None
    clarified: bool = False


class BrandProductionHandoffService:
    """Create the V2 workflow from locked brand decisions."""

    def __init__(
        self,
        database: V2Database,
        workflow_service: WorkflowV2Service | None = None,
    ) -> None:
        self._database = database
        self._workflows = workflow_service
        self._repository = BrandDecisionRepository(database)

    def handoff(self, brand_id: str) -> BrandHandoffResult:
        """Build the planning request from locked decisions and create the workflow."""

        if self._workflows is None:
            raise V2PersistenceError(
                "brand_production_handoff_unavailable",
                "Workflow planning is unavailable for this handoff.",
                stage="brand_production_handoff",
            )

        values = self._repository.get_slot_values(brand_id)
        by_slot = {(value.stage, value.slot_id): value.value for value in values}
        duration_text = by_slot.get(("campaign", "campaign_duration"), "30 seconds")
        aspect = by_slot.get(("campaign", "campaign_aspect_ratio"), "9:16")
        platform = by_slot.get(("campaign", "campaign_platform"), "")
        goal = by_slot.get(("campaign", "campaign_goal"), "")
        audience = by_slot.get(("brand-memory", "brand_audience"), "")
        personality = by_slot.get(("brand-memory", "brand_personality"), "")
        avoid = by_slot.get(("brand-memory", "brand_avoid"), "")
        positioning = by_slot.get(("brand-memory", "brand_positioning"), "")
        adspec = self._repository.get_adspec(brand_id)
        locked_items: list[str] = []
        if adspec is not None:
            locked_items = [item.item_text for item in adspec.items if item.state == "locked"]
        treatment_lines = self._treatment_lines(brand_id)
        brand_name = self._brand_name(brand_id)
        prompt_parts = [
            f"Brand: {brand_name}.",
            f"Brand positioning: {positioning}." if positioning else "",
            f"Target audience: {audience}." if audience else "",
            f"Brand personality: {personality}." if personality else "",
            f"Campaign goal: {goal}." if goal else "",
            f"Platform: {platform}." if platform else "",
            "Locked decisions: " + "; ".join(locked_items) if locked_items else "",
            "Avoid: " + avoid if avoid else "",
            "Treatment:",
            *treatment_lines,
        ]
        prompt = "\n".join(part for part in prompt_parts if part).strip()
        duration = _duration_seconds(duration_text)
        request = WorkflowV2PlanFromPromptRequest(
            prompt=prompt[:4000],
            product_name=brand_name or None,
            duration_seconds=duration,
            aspect_ratio=_aspect_ratio(aspect),
            metadata={"brand_mode": True, "brand_id": brand_id},
        )
        workflow = self._workflows.plan_from_prompt(request)
        if isinstance(workflow, object) and hasattr(workflow, "workflow_id"):
            return BrandHandoffResult(workflow_id=workflow.workflow_id)
        return BrandHandoffResult(workflow_id=None, clarified=True)

    def prepare_guided_production(self, workflow_id: str, brand_id: str) -> None:
        """Project locked Brand decisions into the existing guided journey.

        Brand Professional Mode owns intake until treatment is locked. The
        generic journey must then receive a canonical Requirement Ledger
        revision before its first typed advance; otherwise it has no product
        or media authority and can enqueue an orphaned capability command.
        Workflows created by older fixtures may not have a ledger yet, so the
        projection is intentionally a no-op when that durable authority is
        absent.
        """

        requirements = AgentCanvasRequirementService(
            self._database,
            AgentCanvasRequirementRepository(self._database),
            EventRepository(self._database),
        )
        try:
            current = requirements.get_current_revision(workflow_id)
        except V2PersistenceError as error:
            if error.code == "requirement_ledger_not_found":
                return
            raise

        values = self._repository.get_slot_values(brand_id)
        by_slot = {(value.stage, value.slot_id): value.value for value in values}
        duration_text = by_slot.get(("campaign", "campaign_duration"), "30 seconds")
        aspect_text = by_slot.get(("campaign", "campaign_aspect_ratio"), "9:16")
        positioning = by_slot.get(("brand-memory", "brand_positioning"), "")
        audience = by_slot.get(("brand-memory", "brand_audience"), "")
        treatment_summary = "; ".join(self._treatment_lines(brand_id))
        brand_context = "; ".join(
            item
            for item in (
                f"positioning: {positioning}" if positioning else "",
                f"audience: {audience}" if audience else "",
                f"Locked Brand treatment: {treatment_summary}" if treatment_summary else "",
            )
            if item
        )
        brand_context_text = brand_context or "locked brand decisions"
        source_text = (
            "Brand handoff for the existing advertisement journey: "
            f"{duration_text}; {aspect_text}; one product; a storyboard; a video; BGM audio. "
            f"Locked Brand treatment: {brand_context_text}."
        )
        patch = RequirementPatchV1(
            controls_to_set=(
                DurationSecondsControlPatchV1(
                    value=_duration_seconds(duration_text), source_quote=duration_text
                ),
                AspectRatioControlPatchV1(
                    value=_aspect_ratio(aspect_text), source_quote=aspect_text
                ),
                AudioModeControlPatchV1(value="bgm_only", source_quote="BGM audio"),
                ProductCountControlPatchV1(value=1, source_quote="one product"),
                StoryboardSequenceCountControlPatchV1(value=1, source_quote="a storyboard"),
                VideoSegmentCountControlPatchV1(value=1, source_quote="a video"),
            ),
            directives_to_add=(
                RequirementDirectivePatchV1(
                    source_quote="Locked Brand treatment",
                    normalized_meaning=(
                        "Preserve the locked Brand Professional Mode context in every later "
                        f"creative operation: {brand_context_text}."
                    ),
                    scope_kind="global",
                    strength="hard",
                ),
            ),
        )
        requirements.apply_user_turn_patch(
            workflow_id,
            expected_revision_no=current.revision_no,
            source_turn_id=f"brand-handoff:{brand_id}",
            user_input=source_text,
            patch=patch,
            explicit_elements=(
                RequirementElementPresencePatchV1(
                    element_kind="product", presence="include", source_quote="one product"
                ),
                RequirementElementPresencePatchV1(
                    element_kind="storyboard", presence="include", source_quote="a storyboard"
                ),
                RequirementElementPresencePatchV1(
                    element_kind="video", presence="include", source_quote="a video"
                ),
                RequirementElementPresencePatchV1(
                    element_kind="audio", presence="include", source_quote="BGM audio"
                ),
            ),
        )

    def locked_prohibited_elements(self, brand_id: str) -> tuple[str, ...]:
        return self._repository.locked_prohibited_elements(brand_id)

    def _treatment_lines(self, brand_id: str) -> list[str]:
        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(
                    sql_text(
                        "SELECT step_key, selected_label, detail_text "
                        "FROM brand_treatment_steps WHERE brand_id = :brand_id "
                        "ORDER BY confirmed_at"
                    ),
                    {"brand_id": brand_id},
                ).all()
        except Exception as error:  # noqa: BLE001 - narrow table read
            raise V2PersistenceError(
                "brand_decision_persistence_failed",
                "Treatment read failed.",
                stage="brand_production_handoff",
            ) from error
        return [f"{row[0]}: {row[1]}" + (f" - {row[2]}" if row[2] else "") for row in rows]

    def _brand_name(self, brand_id: str) -> str:
        try:
            with self._database.engine.connect() as connection:
                row = connection.execute(
                    sql_text("SELECT name FROM brands WHERE brand_id = :brand_id"),
                    {"brand_id": brand_id},
                ).first()
        except Exception as error:  # noqa: BLE001 - narrow table read
            raise V2PersistenceError(
                "brand_decision_persistence_failed",
                "Brand read failed.",
                stage="brand_production_handoff",
            ) from error
        return str(row[0]) if row else ""


def _duration_seconds(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    value = int(digits) if digits else 30
    return max(1, min(value, 300))


def _aspect_ratio(value: str) -> str:
    if value in {"16:9", "9:16", "1:1", "4:3", "3:4"}:
        return value
    return "9:16"


def check_locked_elements(text: str, prohibited: tuple[str, ...]) -> None:
    """Deterministic locked-item text check with a stable error code."""

    lowered = text.lower()
    for element in prohibited:
        if element.strip() and element.strip().lower() in lowered:
            raise V2PersistenceError(
                "brand_locked_item_violation",
                f"Prepared prompt contains locked prohibited element: {element}",
                stage="brand_locked_item_check",
            )
