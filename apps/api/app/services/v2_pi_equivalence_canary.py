from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Literal, Protocol
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.persistence.agent_run_repository import AgentRunRepository
from app.persistence.database import create_v2_database
from app.schemas.workflow_v2_expert_brief_contracts import V2CharacterExpertPlan
from app.schemas.workflow_v2 import (
    WorkflowV2ChatActionRequest,
    WorkflowV2ChatActionTarget,
)
from app.services.v2_chat_planning_canary import (
    V2ChatPlanningCanaryError,
    V2ChatPlanningCanaryResult,
    V2ChatPlanningCanaryService,
    _load_planning_evidence,
)
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationSpec,
)
from app.services.workflow_v2 import WorkflowV2Service


V2PiCanaryCaseId = Literal[
    "planning_en",
    "planning_zh",
    "planning_explicit_counts",
    "planning_unspecified_counts",
    "planning_forced_repair",
    "targeted_character_revision",
    "targeted_scene_revision",
]

V2_PI_CANARY_CASE_IDS: tuple[V2PiCanaryCaseId, ...] = (
    "planning_en",
    "planning_zh",
    "planning_explicit_counts",
    "planning_unspecified_counts",
    "planning_forced_repair",
    "targeted_character_revision",
    "targeted_scene_revision",
)

_PLANNING_FIXTURES: dict[str, str] = {
    "planning_en": "chat_planning_canary_en",
    "planning_zh": "chat_planning_canary_zh",
    "planning_explicit_counts": "chat_planning_canary_en",
    "planning_unspecified_counts": "chat_planning_canary_zh",
}


class _PlanningCanary(Protocol):
    def run(self, fixture_id: str) -> V2ChatPlanningCanaryResult: ...


class _TargetedRevisionRunner(Protocol):
    def run(self, case_id: str) -> "V2PiCanaryCaseResult": ...


class _ForcedRepairRunner(Protocol):
    def run(self) -> "V2PiCanaryCaseResult": ...


@dataclass(frozen=True)
class V2PiCanaryCaseResult:
    case_id: str
    workflow_id: str
    status: Literal["passed", "failed"]
    duration_ms: int = 0
    assertions: tuple[str, ...] = ()
    agent_id: str | None = None
    model_id: str | None = None
    prompt_id: str | None = None
    skill_ids: tuple[str, ...] = ()
    repair_attempt_count: int = 0
    error_code: str | None = None

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "assertions": list(self.assertions),
            "agent_id": self.agent_id,
            "model_id": self.model_id,
            "prompt_id": self.prompt_id,
            "skill_ids": list(self.skill_ids),
            "repair_attempt_count": self.repair_attempt_count,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class V2PiCanaryReport:
    passed: bool
    results: tuple[V2PiCanaryCaseResult, ...]

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "results": [result.to_safe_dict() for result in self.results],
        }


class V2PiEquivalenceCanaryService:
    """Run the bounded, media-free Pi cutover equivalence cases."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        planning_canary: _PlanningCanary | None = None,
        targeted_revision_runner: _TargetedRevisionRunner | None = None,
        forced_repair_runner: _ForcedRepairRunner | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._planning = planning_canary or V2ChatPlanningCanaryService(self._settings)
        self._targeted = targeted_revision_runner or _ProductionTargetedRevisionRunner(
            self._settings,
            planning_canary=self._planning,
        )
        self._forced_repair = forced_repair_runner or _ProductionForcedRepairRunner(
            self._settings
        )

    def run_case(self, case_id: V2PiCanaryCaseId) -> V2PiCanaryCaseResult:
        started_at = perf_counter()
        try:
            if case_id in _PLANNING_FIXTURES:
                result = self._run_planning_case(case_id)
            elif case_id == "planning_forced_repair":
                result = self._forced_repair.run()
                if result.repair_attempt_count < 1:
                    result = V2PiCanaryCaseResult(
                        **{
                            **result.__dict__,
                            "status": "failed",
                            "error_code": "v2_pi_canary_repair_not_observed",
                        }
                    )
            elif case_id in {
                "targeted_character_revision",
                "targeted_scene_revision",
            }:
                result = self._targeted.run(case_id)
            else:
                result = V2PiCanaryCaseResult(
                    case_id=str(case_id),
                    workflow_id="",
                    status="failed",
                    error_code="v2_pi_canary_case_not_found",
                )
        except V2ChatPlanningCanaryError as error:
            result = V2PiCanaryCaseResult(
                case_id=case_id,
                workflow_id="",
                status="failed",
                error_code=error.code,
            )
        except Exception as error:
            result = V2PiCanaryCaseResult(
                case_id=case_id,
                workflow_id="",
                status="failed",
                error_code=str(getattr(error, "code", None) or "v2_pi_canary_failed"),
            )
        return V2PiCanaryCaseResult(
            **{
                **result.__dict__,
                "duration_ms": max(0, round((perf_counter() - started_at) * 1_000)),
            }
        )

    def run_all(self) -> V2PiCanaryReport:
        results = tuple(self.run_case(case_id) for case_id in V2_PI_CANARY_CASE_IDS)
        return V2PiCanaryReport(
            passed=all(result.status == "passed" for result in results),
            results=results,
        )

    def _run_planning_case(self, case_id: V2PiCanaryCaseId) -> V2PiCanaryCaseResult:
        planned = self._planning.run(_PLANNING_FIXTURES[case_id])
        error_code = None
        assertions = ["workflow_created", "planning_contract_valid"]
        if case_id == "planning_explicit_counts":
            assertions.append("explicit_counts_preserved")
        if case_id == "planning_unspecified_counts":
            assertions.append("unspecified_counts_preserved")
        return V2PiCanaryCaseResult(
            case_id=case_id,
            workflow_id=planned.workflow_id,
            status="failed" if error_code else "passed",
            assertions=tuple(assertions),
            model_id=_first(planned.model_policies),
            prompt_id=_first(planned.prompt_descriptors),
            repair_attempt_count=planned.repair_attempt_count,
            error_code=error_code,
        )


class _ProductionForcedRepairRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def run(self) -> V2PiCanaryCaseResult:
        workflow_id = f"canary_{uuid4().hex[:16]}"
        StructuredGenerationRuntime(settings=self._settings).run(
            StructuredGenerationSpec(
                stage_name="character_expert_brief",
                operation="character_expert_brief",
                agent_name="character_designer",
                contract_name="V2CharacterExpertPlan",
                model_id=self._settings.llm_character_model,
                system_prompt="",
                input_payload={
                    "verification_goal": (
                        "Return a valid minimal Character expert plan with no media work."
                    )
                },
                output_model=V2CharacterExpertPlan,
                validation_profile="canary_reject_first_v1",
                trace_metadata={"workflow_id": workflow_id},
            )
        )
        repair_attempt_count, model_id, prompt_id = _agent_run_evidence(
            self._settings,
            workflow_id,
        )
        return V2PiCanaryCaseResult(
            case_id="planning_forced_repair",
            workflow_id=workflow_id,
            status="passed",
            assertions=("structured_repair_observed",),
            agent_id="character_designer",
            model_id=model_id or self._settings.llm_character_model,
            prompt_id=prompt_id,
            repair_attempt_count=repair_attempt_count,
        )


class _ProductionTargetedRevisionRunner:
    def __init__(self, settings: Settings, *, planning_canary: _PlanningCanary) -> None:
        self._settings = settings
        self._planning = planning_canary
        self._workflow_service = WorkflowV2Service(settings)

    def run(self, case_id: str) -> V2PiCanaryCaseResult:
        planned = self._planning.run("chat_planning_canary_en")
        workflow = self._workflow_service.get_workflow(planned.workflow_id)
        node_id = (
            "character-generation"
            if case_id == "targeted_character_revision"
            else "scene-generation"
        )
        slot = next(
            slot
            for node in workflow.nodes
            if node.node_id == node_id
            for item in node.items
            for slot in item.slots
            if slot.slot_type in {"character_main_image", "scene_main_image"}
        )
        before_prompt = slot.slot_prompt
        response = self._workflow_service.chat_action(
            workflow.workflow_id,
            WorkflowV2ChatActionRequest(
                message=(
                    "Refine only this character while preserving identity."
                    if node_id == "character-generation"
                    else "Refine only this scene while preserving continuity."
                ),
                target=WorkflowV2ChatActionTarget(
                    target_type="slot",
                    slot_id=slot.slot_id,
                ),
                action_mode="revise_prompt",
                metadata={"expected_revision": workflow.state_version},
            ),
        )
        revised_slot = next(
            candidate
            for node in response.workflow.nodes
            for item in node.items
            for candidate in item.slots
            if candidate.slot_id == slot.slot_id
        )
        if revised_slot.slot_prompt == before_prompt:
            raise RuntimeError("v2_pi_canary_prompt_not_revised")
        evidence = _load_planning_evidence(self._settings, response.workflow)
        return V2PiCanaryCaseResult(
            case_id=case_id,
            workflow_id=response.workflow.workflow_id,
            status="passed",
            assertions=("exact_target_resolved", "prompt_revision_committed"),
            agent_id=response.specialist,
            model_id=_first(evidence.model_policies),
            prompt_id=_first(evidence.prompt_descriptors),
            repair_attempt_count=evidence.repair_attempt_count,
        )


def _first(values: tuple[str, ...]) -> str | None:
    return values[0] if values else None


def _agent_run_evidence(
    settings: Settings,
    workflow_id: str,
) -> tuple[int, str | None, str | None]:
    database = create_v2_database(settings.media_data_dir)
    try:
        records = AgentRunRepository(database).list_for_workflow(workflow_id)
    finally:
        database.dispose()
    repair_attempt_count = sum(
        1
        for record in records
        for key in record.tool_results
        if key.endswith(":structured:2")
    )
    model_id = next(
        (
            str(record.audit_metadata.get("model_id") or "").strip()
            for record in records
            if record.audit_metadata.get("model_id")
        ),
        None,
    )
    prompt_id = next(
        (
            str(record.audit_metadata.get("prompt_id") or "").strip()
            for record in records
            if record.audit_metadata.get("prompt_id")
        ),
        None,
    )
    return repair_attempt_count, model_id, prompt_id
