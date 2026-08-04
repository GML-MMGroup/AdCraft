import json
from time import perf_counter
from typing import Any, Callable

from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.agent_runtime import AgentRunPolicy
from app.schemas.specialist_agents import (
    SpecialistAgentName,
    SpecialistAgentOutcome,
    SpecialistInvocationRequest,
    SpecialistResult,
)
from app.services.agent_trace import AgentTraceWriter, utc_now
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)

SPECIALIST_BY_NODE_TYPE: dict[str, SpecialistAgentName] = {
    "script": "script_writer",
    "character-generation": "character_designer",
    "scene-generation": "scene_designer",
    "storyboard": "storyboard_artist",
    "storyboard-video-generation": "video_director",
    "bgm": "sound_director",
}

_SPECIALIST_DISPLAY_NAME: dict[str, str] = {
    "script_writer": "Script Writer",
    "character_designer": "Character Designer",
    "scene_designer": "Scene Designer",
    "storyboard_artist": "Storyboard Artist",
    "video_director": "Video Director",
    "sound_director": "Sound Director",
}


class SpecialistAgentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SpecialistAgentService:
    def __init__(
        self,
        settings: Settings,
        *,
        trace_writer_factory: Callable[[Any, str], AgentTraceWriter] = AgentTraceWriter,
    ) -> None:
        self._settings = settings
        self._trace_writer_factory = trace_writer_factory
        self._structured_runtime = StructuredGenerationRuntime(settings=settings)

    def invoke(self, request: SpecialistInvocationRequest) -> SpecialistAgentOutcome:
        started_at = utc_now()
        started_counter = perf_counter()
        outcome: SpecialistAgentOutcome | None = None
        error: str | None = None
        try:
            if self._settings.agent_runtime_mode == "fake":
                outcome = SpecialistAgentOutcome(
                    result=self._mock_result(request),
                    used_fallback=False,
                    model_id=None,
                )
            else:
                outcome = self._real_outcome(request)
            return outcome
        except SpecialistAgentError as exc:
            error = f"{exc.code}: {exc}"
            raise
        finally:
            self._trace_specialist(
                request,
                outcome,
                error=error,
                started_at=started_at,
                duration_ms=round((perf_counter() - started_counter) * 1000),
            )

    def normalize_result(
        self,
        request: SpecialistInvocationRequest,
        payload: dict[str, Any],
    ) -> SpecialistResult:
        try:
            result = SpecialistResult.model_validate(payload)
        except ValidationError as exc:
            raise SpecialistAgentError(
                "specialist_output_invalid",
                str(exc),
            ) from exc
        if result.specialist != request.specialist:
            raise SpecialistAgentError(
                "specialist_output_invalid",
                (
                    f"Specialist output was produced by {result.specialist}, "
                    f"not {request.specialist}."
                ),
            )
        if not _targets_match(request.target, result.target):
            raise SpecialistAgentError(
                "specialist_target_mismatch",
                "Specialist output target does not match the requested canvas target.",
            )
        if not _result_type_supported(request, result):
            raise SpecialistAgentError(
                "specialist_action_unsupported",
                (
                    f"Specialist result_type {result.result_type} cannot be applied "
                    f"to action {request.action}."
                ),
            )
        return result.model_copy(update={"target": request.target})

    def _real_outcome(self, request: SpecialistInvocationRequest) -> SpecialistAgentOutcome:
        payload, model_id = self._run_real_specialist_payload(request)
        return SpecialistAgentOutcome(
            result=self.normalize_result(request, payload),
            used_fallback=False,
            model_id=model_id,
        )

    def _run_real_specialist_payload(
        self,
        request: SpecialistInvocationRequest,
    ) -> tuple[dict[str, Any], str | None]:
        try:
            output = self._structured_runtime.run(
                StructuredGenerationSpec(
                    stage_name="targeted_revision",
                    operation="targeted_revision",
                    agent_name=_pi_agent_name(request.specialist),
                    contract_name="SpecialistResult",
                    tool_mode="structured_only",
                    policy=AgentRunPolicy(
                        timeout_seconds=600.0,
                        max_output_bytes=1_048_576,
                        max_event_bytes=1_048_576,
                    ),
                    model_id=_model_id_for_specialist(request.specialist, self._settings),
                    system_prompt="",
                    input_payload=_request_context(request),
                    output_model=SpecialistResult,
                    quality_validator=lambda candidate: self.normalize_result(
                        request,
                        candidate.model_dump(mode="json"),
                    ),
                    trace_metadata={
                        "workflow_id": request.workflow_id,
                        "conversation_id": request.conversation_id,
                        "action_id": request.constraints.get("action_id"),
                        "expected_target_revision": request.constraints.get("expected_revision"),
                        "node_id": request.target.node_id,
                        "item_id": request.target.item_id,
                    },
                )
            ).output
            return (
                self.normalize_result(
                    request,
                    output.model_dump(mode="json"),
                ).model_dump(mode="json"),
                _model_id_for_specialist(request.specialist, self._settings),
            )
        except StructuredGenerationRuntimeError as exc:
            code = (
                "specialist_real_mode_unavailable"
                if exc.code == "structured_generation_unavailable"
                else "specialist_execution_failed"
            )
            raise SpecialistAgentError(code, str(exc)) from exc
        except SpecialistAgentError:
            raise
        except Exception as exc:  # noqa: BLE001 - returned as controlled specialist error.
            raise SpecialistAgentError(
                "specialist_execution_failed",
                str(exc),
            ) from exc

    def _mock_result(
        self,
        request: SpecialistInvocationRequest,
        *,
        warnings: list[dict[str, Any]] | None = None,
    ) -> SpecialistResult:
        result_type = _mock_result_type(request)
        display = _SPECIALIST_DISPLAY_NAME[request.specialist]
        user_instruction = request.user_instruction.strip()
        current_prompt = (request.current_prompt or "").strip()
        if result_type in {"revised_node_prompt", "revised_item_prompt"}:
            prefix = f"{display} refinement"
            revised_prompt = (
                f"{current_prompt}\n\n{prefix}: {user_instruction}"
                if current_prompt
                else f"{prefix}: {user_instruction}"
            )
            revision_instruction = None
        else:
            revised_prompt = None
            revision_instruction = f"{display} revision instruction: {user_instruction}"
        return SpecialistResult(
            specialist=request.specialist,
            target=request.target,
            result_type=result_type,
            revised_prompt=revised_prompt,
            revision_instruction=revision_instruction,
            negative_prompt="low quality, off-brand, inconsistent continuity",
            quality_notes=[
                f"Deterministic {display} mock output.",
                "Apply through the workflow action service before running media generation.",
            ],
            reference_requirements=[],
            warnings=list(warnings or []),
            mock_mode=True,
        )

    def _trace_specialist(
        self,
        request: SpecialistInvocationRequest,
        outcome: SpecialistAgentOutcome | None,
        *,
        error: str | None,
        started_at: Any,
        duration_ms: int,
    ) -> None:
        result = outcome.result if outcome is not None else None
        writer = self._trace_writer_factory(self._settings.media_data_dir, request.workflow_id)
        writer.append(
            agent=request.specialist,
            model=outcome.model_id if outcome is not None else None,
            prompt=json.dumps(_request_context(request), ensure_ascii=False),
            output=result.model_dump(mode="json") if result is not None else None,
            error=error,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=duration_ms,
            metadata={
                "trace_role": "agent",
                "specialist": request.specialist,
                "workflow_id": request.workflow_id,
                "conversation_id": request.conversation_id,
                "target": request.target.model_dump(mode="json"),
                "action": request.action,
                "result_type": result.result_type if result is not None else None,
                "model_id": outcome.model_id if outcome is not None else None,
                "used_fallback": outcome.used_fallback if outcome is not None else False,
                "warnings": result.warnings if result is not None else [],
            },
        )


def specialist_for_node_type(node_type: str) -> SpecialistAgentName | None:
    return SPECIALIST_BY_NODE_TYPE.get(node_type)


def _pi_agent_name(specialist: SpecialistAgentName) -> str:
    return "bgm_director" if specialist == "sound_director" else specialist


def _model_id_for_specialist(specialist: SpecialistAgentName, settings: Settings) -> str:
    return {
        "script_writer": settings.llm_script_model,
        "character_designer": settings.llm_character_model,
        "scene_designer": settings.llm_scene_model,
        "storyboard_artist": settings.llm_storyboard_model,
        "video_director": settings.llm_final_video_model,
        "sound_director": settings.llm_bgm_model,
    }[specialist]


def _mock_result_type(request: SpecialistInvocationRequest) -> str:
    action = request.action
    if "run_item_only" in action:
        return "revision_instruction"
    if request.target.target_type == "item" or "item" in action:
        return "revised_item_prompt"
    return "revised_node_prompt"


def _request_context(request: SpecialistInvocationRequest) -> dict[str, Any]:
    return {
        "workflow_id": request.workflow_id,
        "conversation_id": request.conversation_id,
        "specialist": request.specialist,
        "action": request.action,
        "target": request.target.model_dump(mode="json"),
        "user_instruction": request.user_instruction,
        "current_prompt": request.current_prompt,
        "director_context_summary": request.director_context_summary,
        "script_context_summary": request.script_context_summary,
        "target_item_context": request.target_item_context,
        "target_asset_summary": request.target_asset_summary,
        "reference_asset_summary": request.reference_asset_summary,
        "memory_summary": request.memory_summary,
        "constraints": request.constraints,
    }


def _targets_match(left: Any, right: Any) -> bool:
    for field in ("workflow_id", "target_type", "node_id", "item_id", "asset_id"):
        if getattr(left, field, None) != getattr(right, field, None):
            return False
    left_semantic = getattr(left, "semantic_type", None)
    right_semantic = getattr(right, "semantic_type", None)
    return not (left_semantic and right_semantic and left_semantic != right_semantic)


def _result_type_supported(
    request: SpecialistInvocationRequest,
    result: SpecialistResult,
) -> bool:
    if request.target.target_type == "item" or "item" in request.action:
        return result.result_type in {"revised_item_prompt", "revision_instruction"}
    if request.target.target_type == "node":
        return result.result_type in {"revised_node_prompt", "quality_notes"}
    return result.result_type in {"revision_instruction", "quality_notes", "reference_requirements"}
