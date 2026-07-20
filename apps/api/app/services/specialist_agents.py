import json
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from app.agents.advertising import (
    build_bgm_agent,
    build_character_designer_agent,
    build_final_video_generation_agent,
    build_scene_designer_agent,
    build_script_writer_agent,
    build_storyboard_agent,
)
from app.core.config import Settings
from app.schemas.specialist_agents import (
    SpecialistAgentName,
    SpecialistAgentOutcome,
    SpecialistInvocationRequest,
    SpecialistResult,
)
from app.services.agno_orchestrator import _run_agent
from app.services.agent_trace import AgentTraceWriter, utc_now

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
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def invoke(self, request: SpecialistInvocationRequest) -> SpecialistAgentOutcome:
        started_at = utc_now()
        started_counter = perf_counter()
        outcome: SpecialistAgentOutcome | None = None
        error: str | None = None
        try:
            if self._settings.agno_mock_mode:
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
        return result

    def _real_outcome(self, request: SpecialistInvocationRequest) -> SpecialistAgentOutcome:
        try:
            payload, model_id = self._run_real_specialist_payload(request)
            return SpecialistAgentOutcome(
                result=self.normalize_result(request, payload),
                used_fallback=False,
                model_id=model_id,
            )
        except SpecialistAgentError as exc:
            if request.require_real_specialist or exc.code not in {
                "specialist_real_mode_unavailable",
                "specialist_execution_failed",
            }:
                raise
            warning = {
                "code": "specialist_real_mode_fallback",
                "message": (
                    "Real specialist agent is unavailable; deterministic fallback was used."
                ),
            }
            result = self._mock_result(request, warnings=[warning])
            return SpecialistAgentOutcome(result=result, used_fallback=True, model_id=None)

    def _run_real_specialist_payload(
        self,
        request: SpecialistInvocationRequest,
    ) -> tuple[dict[str, Any], str | None]:
        try:
            agent = _build_specialist_agent(request.specialist, self._settings)
        except Exception as exc:  # noqa: BLE001 - normalized for API callers.
            raise SpecialistAgentError(
                "specialist_real_mode_unavailable",
                str(exc),
            ) from exc
        task = (
            "Act as the named advertising specialist. Return a bounded structured result for "
            "the requested canvas target. Do not mutate workflow state, do not start media "
            "generation, and do not include sibling item prompts."
        )
        context = _request_context(request)
        try:
            output = _run_agent(
                agent=agent,
                output_model=SpecialistResult,
                task=task,
                context=context,
                trace_writer=AgentTraceWriter(
                    self._settings.media_data_dir,
                    request.workflow_id,
                ),
                node_id=request.target.node_id,
            )
            return output.model_dump(mode="json"), getattr(agent.model, "id", None)
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
        writer = AgentTraceWriter(self._settings.media_data_dir, request.workflow_id)
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


def _build_specialist_agent(specialist: str, settings: Settings) -> Any:
    if specialist == "script_writer":
        return build_script_writer_agent(settings)
    if specialist == "character_designer":
        return build_character_designer_agent(settings)
    if specialist == "scene_designer":
        return build_scene_designer_agent(settings)
    if specialist == "storyboard_artist":
        return build_storyboard_agent(settings)
    if specialist == "video_director":
        return build_final_video_generation_agent(settings)
    if specialist == "sound_director":
        return build_bgm_agent(settings)
    raise SpecialistAgentError(
        "specialist_not_supported",
        f"Specialist is not supported: {specialist}.",
    )


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
