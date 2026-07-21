from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.schemas.front_desk import FrontDeskChatRequest
from app.schemas.workflow_v2 import WorkflowV2, WorkflowV2PlanFromChatResponse
from app.schemas.workflow_v2_production_acceptance import (
    V2ProductionAcceptanceFailure,
    V2ProductionAcceptanceFixture,
)
from app.services.front_desk import FrontDeskService
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_input_assets import V2InputAssetService, asset_locator
from app.services.v2_production_acceptance_fixtures import (
    V2ProductionAcceptanceFixtureRegistry,
)
from app.services.workflow_v2 import WorkflowV2Error, WorkflowV2Service


DEFAULT_CHAT_PLANNING_CANARY_FIXTURE = "chat_planning_canary"


class _PlanningWorkflowService(Protocol):
    def plan_from_chat(
        self,
        request: FrontDeskChatRequest,
        front_desk_service: FrontDeskService | None = None,
    ) -> WorkflowV2PlanFromChatResponse: ...


class _PlanningValidator(Protocol):
    def validate(
        self,
        fixture: V2ProductionAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> list[V2ProductionAcceptanceFailure]: ...


class V2ChatPlanningCanaryError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class V2ChatPlanningCanaryResult:
    fixture_id: str
    workflow_id: str
    input_asset_count: int
    planning_valid: bool = True


class V2ChatPlanningCanaryValidator:
    def validate(
        self,
        fixture: V2ProductionAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> list[V2ProductionAcceptanceFailure]:
        failures: list[V2ProductionAcceptanceFailure] = []
        nodes = {node.node_id: node for node in workflow.nodes}
        for node_id in fixture.required_nodes:
            if node_id not in nodes:
                failures.append(
                    _planning_failure(
                        fixture,
                        "acceptance_missing_required_node",
                        f"Missing required node: {node_id}",
                        node_id=node_id,
                    )
                )

        script_plan = workflow.metadata.get("script_plan")
        script_shots = script_plan.get("shots") if isinstance(script_plan, dict) else []
        expected_counts = fixture.expected_counts.model_dump()
        actual_counts = {
            "product_count": _item_count(workflow, "product"),
            "character_count": _item_count(workflow, "character"),
            "scene_count": _item_count(workflow, "scene"),
            "storyboard_shot_count": len(script_shots) if isinstance(script_shots, list) else 0,
        }
        for field_name, expected in expected_counts.items():
            actual = actual_counts[field_name]
            if actual != expected:
                failures.append(
                    _planning_failure(
                        fixture,
                        "acceptance_explicit_count_mismatch",
                        f"{field_name} expected {expected}, got {actual}.",
                    )
                )

        for node in workflow.nodes:
            for item in node.items:
                required_slots = fixture.required_slot_types.get(item.item_type, [])
                available_slots = {slot.slot_type for slot in item.slots}
                for slot_type in required_slots:
                    if slot_type not in available_slots:
                        failures.append(
                            _planning_failure(
                                fixture,
                                "acceptance_missing_required_slot",
                                f"Missing required slot: {slot_type}",
                                node_id=node.node_id,
                                item_id=item.item_id,
                                slot_id=f"{item.item_id}:{slot_type}",
                            )
                        )
        return failures


class V2ChatPlanningCanaryService:
    """Runs a credentialed chat-planning canary without crossing into execution."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        fixture_registry: V2ProductionAcceptanceFixtureRegistry | None = None,
        input_assets: V2InputAssetService | None = None,
        workflow_service: _PlanningWorkflowService | None = None,
        front_desk_service: FrontDeskService | None = None,
        planning_validator: _PlanningValidator | None = None,
        require_real_agents: bool = True,
    ) -> None:
        self._settings = settings or get_settings()
        self._fixtures = fixture_registry or V2ProductionAcceptanceFixtureRegistry()
        self._input_assets = input_assets or V2InputAssetService(settings=self._settings)
        self._workflow_service = workflow_service or WorkflowV2Service(self._settings)
        self._front_desk = front_desk_service or FrontDeskService(self._settings)
        self._planning_validator = planning_validator or V2ChatPlanningCanaryValidator()
        self._require_real_agents = require_real_agents

    def run(
        self,
        fixture_id: str = DEFAULT_CHAT_PLANNING_CANARY_FIXTURE,
    ) -> V2ChatPlanningCanaryResult:
        if self._require_real_agents and self._settings.agno_mock_mode:
            raise V2ChatPlanningCanaryError(
                "v2_chat_planning_canary_requires_real_agents",
                "The chat-planning canary requires real agent mode.",
            )

        bundle = self._fixtures.load(fixture_id)
        declarations = {asset.relative_path: asset for asset in bundle.fixture.input_assets}
        locators = list(bundle.fixture.request.input_asset_locators)
        for relative_path, path in bundle.asset_paths.items():
            declaration = declarations[relative_path]
            record = self._input_assets.save_asset_bytes(
                body=path.read_bytes(),
                filename=path.name,
                content_type=declaration.content_type,
                semantic_type=declaration.intent,
                display_name=declaration.display_name,
                intent=declaration.intent,
                metadata={
                    "origin": "v2_chat_planning_canary_fixture",
                    "fixture_id": fixture_id,
                },
            )
            locators.append(asset_locator(record.asset_id, record.version_id))

        request = FrontDeskChatRequest(
            message=bundle.fixture.request.prompt,
            audio_mode=bundle.fixture.request.audio_mode,
            input_asset_locators=locators,
            reference_mode=bundle.fixture.request.reference_mode,
            workflow_schema_version=2,
            metadata={
                "source": "v2_chat_planning_canary",
                "fixture_id": fixture_id,
            },
        )
        try:
            planned = self._workflow_service.plan_from_chat(
                request,
                front_desk_service=self._front_desk,
            )
        except WorkflowV2Error as exc:
            safe_details = sanitize_context_for_llm_text(exc.details)
            raise V2ChatPlanningCanaryError(
                exc.code,
                "The chat-planning canary failed during workflow planning.",
                details=safe_details if isinstance(safe_details, dict) else {},
            ) from exc
        if planned.workflow is None:
            raise V2ChatPlanningCanaryError(
                planned.error_code or "v2_chat_planning_canary_workflow_missing",
                planned.message or "The chat-planning canary did not create a workflow.",
                details=planned.details,
            )

        failures = self._planning_validator.validate(bundle.fixture, planned.workflow)
        if failures:
            failure = failures[0]
            raise V2ChatPlanningCanaryError(
                "v2_chat_planning_canary_validation_failed",
                failure.message,
                details={"failure": failure.model_dump(mode="json")},
            )

        return V2ChatPlanningCanaryResult(
            fixture_id=fixture_id,
            workflow_id=planned.workflow.workflow_id,
            input_asset_count=len(locators),
        )


def _item_count(workflow: WorkflowV2, item_type: str) -> int:
    return sum(1 for node in workflow.nodes for item in node.items if item.item_type == item_type)


def _planning_failure(
    fixture: V2ProductionAcceptanceFixture,
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    item_id: str | None = None,
    slot_id: str | None = None,
) -> V2ProductionAcceptanceFailure:
    return V2ProductionAcceptanceFailure(
        code=code,
        stage="planning",
        message=message,
        node_id=node_id,
        item_id=item_id,
        slot_id=slot_id,
        evidence={"fixture_id": fixture.fixture_id},
    )
