from collections.abc import Callable
from typing import Any

from app.core.config import Settings
from app.schemas.agent_outputs import CharacterDesignOutput, SceneDesignOutput, ScriptOutput
from app.schemas.workflow_nodes import WorkflowNodeRunRequest
from app.services.agent_trace import AgentTraceWriter
from app.services.agno_orchestrator import _run_agent
from app.services.final_composition_timeline import (
    FinalCompositionTimelineError,
    FinalCompositionTimelineService,
)
from app.services.workflow_node_direct_outputs import (
    ad_request_for_direct_node,
    bgm_output,
    creative_direction_output,
    mock_agent_output,
    product_design_output,
    requirements_analysis_output,
    storyboard_scenes,
    task_with_override,
    with_override_in_character_design,
    with_override_in_scene_design,
    with_override_in_storyboard_scenes,
)
from app.services.workflow_media_segments import (
    final_composition_waiting_output,
    load_workflow_segments,
    segment_is_ready,
)
from app.services.workflow_node_errors import WorkflowNodeInputError
from app.services.workflow_node_media_generators import (
    generate_character_media_output,
    generate_product_media_output,
    generate_scene_media_output,
    generate_storyboard_media_output,
    generate_storyboard_video_media_output,
    merge_prompt_optimization,
    product_design_from_provider_prompt,
    product_reference_asset_ids_from_context,
    product_reference_missing_output,
)
from app.services.workflow_node_prompt_runtime import (
    optimize_generation_prompt,
    prompt_optimization_failed,
)
from app.services.workflow_node_provider_factory import build_media_provider
from app.services.workflow_provider_runtime import (
    WorkflowProviderRuntime,
    accepted_reference_assets,
    output_with_reference_policy,
    provider_input_assets,
)
from app.services.workflow_shot_bindings import (
    build_storyboard_binding_plan,
    build_storyboard_video_binding_plan,
    storyboard_binding_failure_output,
)
from app.skills.registry import CORE_AGENT_BY_NODE, augment_context_with_skills, record_skill_trace
from app.teams.advertising import build_advertising_team


OPTIMIZER_AGENT_BY_NODE: dict[str, str] = {
    "product-generation": "Product Designer Agent",
    "character-generation": "Character Designer Agent",
    "scene-generation": "Scene Designer Agent",
    "storyboard": "Storyboard Agent",
    "storyboard-video-generation": "Video Generation / Composition Agent",
    "bgm": "BGM Agent",
}


class WorkflowNodeExecutor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider_runtime = WorkflowProviderRuntime(settings)
        self._handlers: dict[
            str,
            Callable[[WorkflowNodeRunRequest, str, list[dict[str, Any]]], dict[str, Any]],
        ] = {
            "requirements-analysis": self._requirements_analysis,
            "product-design": self._product_design,
            "creative-direction": self._creative_direction,
            "script": self._agent_node,
            "product-generation": self._product_generation,
            "character-generation": self._character_generation,
            "scene-generation": self._scene_generation,
            "storyboard": self._storyboard,
            "storyboard-video-generation": self._storyboard_video_generation,
            "bgm": self._bgm,
            "character-image-generation": self._character_image_generation,
            "scene-image-generation": self._scene_image_generation,
            "storyboard-image-generation": self._storyboard_image_generation,
            "final-composition": self._final_composition,
            "character-design": self._agent_node,
            "scene-design": self._agent_node,
        }

    def supports_node_type(self, node_type: str) -> bool:
        return node_type in self._handlers

    def execute(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if request.optimize_only:
            return self._optimize_only(request, workflow_id, input_assets)
        handler = self._handlers.get(request.node_type)
        if handler is None:
            raise WorkflowNodeInputError(f"unsupported node_type: {request.node_type}")
        return handler(request, workflow_id, input_assets)

    def _optimize_only(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        reference_policy = self._provider_runtime.apply_reference_policy_to_request(
            request,
            workflow_id,
        )
        if request.node_type not in OPTIMIZER_AGENT_BY_NODE:
            raise WorkflowNodeInputError(
                "prompt_optimizer_not_supported: "
                f"node_type does not support optimize_only: {request.node_type}"
            )
        optimization = optimize_generation_prompt(
            request,
            input_assets,
            workflow_id,
            self._settings,
        )
        return output_with_reference_policy(optimization, reference_policy)

    def _requirements_analysis(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        _input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return requirements_analysis_output(
            request,
            workflow_id,
            self._settings,
        )

    def _product_design(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        _input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ad_request = ad_request_for_direct_node(request, workflow_id, self._settings)
        return product_design_output(ad_request, request.input_context["requirements"])

    def _creative_direction(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        _input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ad_request = ad_request_for_direct_node(request, workflow_id, self._settings)
        return creative_direction_output(ad_request, request.input_context)

    def _bgm(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ad_request = ad_request_for_direct_node(request, workflow_id, self._settings)
        optimization = optimize_generation_prompt(
            request,
            input_assets,
            workflow_id,
            self._settings,
        )
        if prompt_optimization_failed(optimization):
            return optimization
        media_output = self._provider_runtime.execute_provider_strategy(
            request=request,
            workflow_id=workflow_id,
            media_type="audio",
            generator=lambda attempt_request, _provider: bgm_output(
                ad_request,
                {
                    **attempt_request.input_context,
                    "override_prompt": attempt_request.input_context["provider_prompt"],
                    "reference_assets": accepted_reference_assets(attempt_request.input_context),
                },
            ),
        )
        return merge_prompt_optimization(
            media_output,
            optimization,
            request.node_type,
            workflow_id,
        )

    def _agent_node(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        _input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        trace_writer = AgentTraceWriter(self._settings.media_data_dir, workflow_id)
        if self._settings.agno_mock_mode:
            record_skill_trace(
                node_id=request.node_type,
                core_agent_name=CORE_AGENT_BY_NODE.get(request.node_type, request.node_type),
                context=request.input_context,
                trace_writer=trace_writer,
                mock_mode=True,
            )
            return mock_agent_output(
                request.node_type,
                request.input_context,
                request.override_prompt,
            )
        team = build_advertising_team(self._settings)
        members = {member.name: member for member in team.members if getattr(member, "name", None)}
        if request.node_type == "script":
            output = _run_agent(
                members["Script Writer Agent"],
                ScriptOutput,
                task_with_override(
                    (
                        "Write a short advertising script with a hook, product showcase, "
                        "call to action, and 4-6 ordered shot_beats for the requested duration."
                    ),
                    request.override_prompt,
                ),
                augment_context_with_skills(
                    node_id=request.node_type,
                    core_agent_name=CORE_AGENT_BY_NODE["script"],
                    context=request.input_context,
                    trace_writer=trace_writer,
                    mock_mode=False,
                ),
                trace_writer,
                request.node_type,
            )
        elif request.node_type == "character-design":
            output = _run_agent(
                members["Character Designer Agent"],
                CharacterDesignOutput,
                task_with_override(
                    "Design brand-aligned characters for the advertising short film.",
                    request.override_prompt,
                ),
                augment_context_with_skills(
                    node_id=request.node_type,
                    core_agent_name=CORE_AGENT_BY_NODE["character-design"],
                    context=request.input_context,
                    trace_writer=trace_writer,
                    mock_mode=False,
                ),
                trace_writer,
                request.node_type,
            )
        elif request.node_type == "scene-design":
            output = _run_agent(
                members["Scene Designer Agent"],
                SceneDesignOutput,
                task_with_override(
                    (
                        "Design at least 3 distinct scene specs with stable scene_id values "
                        "from the script shot_beats, unless the script explicitly uses one location."
                    ),
                    request.override_prompt,
                ),
                augment_context_with_skills(
                    node_id=request.node_type,
                    core_agent_name=CORE_AGENT_BY_NODE["scene-design"],
                    context=request.input_context,
                    trace_writer=trace_writer,
                    mock_mode=False,
                ),
                trace_writer,
                request.node_type,
            )
        else:
            raise WorkflowNodeInputError(f"unsupported agent node_type: {request.node_type}")
        return output.model_dump()

    def _product_generation(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        optimization = optimize_generation_prompt(
            request,
            input_assets,
            workflow_id,
            self._settings,
        )
        if prompt_optimization_failed(optimization):
            return optimization
        missing_reference = product_reference_missing_output(
            product_design_from_provider_prompt(
                str(request.input_context.get("provider_prompt") or ""),
                request.input_context,
            ),
            fallback_reference_asset_ids=product_reference_asset_ids_from_context(
                request.input_context
            ),
        )
        if missing_reference is not None:
            return merge_prompt_optimization(
                missing_reference,
                optimization,
                request.node_type,
                workflow_id,
            )
        media_output = self._provider_runtime.execute_provider_strategy(
            request=request,
            workflow_id=workflow_id,
            media_type="image",
            generator=lambda attempt_request, provider: generate_product_media_output(
                provider,
                attempt_request.input_context,
                workflow_id,
            ),
        )
        return merge_prompt_optimization(
            media_output,
            optimization,
            request.node_type,
            workflow_id,
        )

    def _character_generation(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        optimization = optimize_generation_prompt(
            request,
            input_assets,
            workflow_id,
            self._settings,
        )
        if prompt_optimization_failed(optimization):
            return optimization
        media_output = self._provider_runtime.execute_provider_strategy(
            request=request,
            workflow_id=workflow_id,
            media_type="image",
            generator=lambda attempt_request, provider: generate_character_media_output(
                provider,
                attempt_request.input_context,
                workflow_id,
            ),
        )
        return merge_prompt_optimization(
            media_output,
            optimization,
            request.node_type,
            workflow_id,
        )

    def _scene_generation(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        optimization = optimize_generation_prompt(
            request,
            input_assets,
            workflow_id,
            self._settings,
        )
        if prompt_optimization_failed(optimization):
            return optimization
        media_output = self._provider_runtime.execute_provider_strategy(
            request=request,
            workflow_id=workflow_id,
            media_type="image",
            generator=lambda attempt_request, provider: generate_scene_media_output(
                provider,
                attempt_request.input_context,
                workflow_id,
            ),
        )
        return merge_prompt_optimization(
            media_output,
            optimization,
            request.node_type,
            workflow_id,
        )

    def _storyboard(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        optimization = optimize_generation_prompt(
            request,
            input_assets,
            workflow_id,
            self._settings,
        )
        if prompt_optimization_failed(optimization):
            return optimization
        storyboard_input_assets = provider_input_assets(input_assets, request.input_context)
        binding_plan = build_storyboard_binding_plan(
            request.input_context,
            storyboard_input_assets,
            str(request.input_context.get("provider_prompt") or ""),
        )
        if binding_plan.get("error"):
            return self._binding_failure_output(
                binding_plan,
                optimization,
                request.node_type,
                workflow_id,
            )
        media_output = self._provider_runtime.execute_provider_strategy(
            request=request,
            workflow_id=workflow_id,
            media_type="image",
            generator=lambda attempt_request, provider: generate_storyboard_media_output(
                provider,
                attempt_request.input_context,
                provider_input_assets(input_assets, attempt_request.input_context),
                workflow_id,
                binding_plan,
            ),
        )
        return merge_prompt_optimization(
            media_output,
            optimization,
            request.node_type,
            workflow_id,
        )

    def _storyboard_video_generation(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        optimization = optimize_generation_prompt(
            request,
            input_assets,
            workflow_id,
            self._settings,
        )
        if prompt_optimization_failed(optimization):
            return optimization
        storyboard_video_input_assets = provider_input_assets(input_assets, request.input_context)
        binding_plan = build_storyboard_video_binding_plan(
            request.input_context,
            storyboard_video_input_assets,
            str(request.input_context.get("provider_prompt") or ""),
        )
        if binding_plan.get("error"):
            return self._binding_failure_output(
                binding_plan,
                optimization,
                request.node_type,
                workflow_id,
            )
        media_output = self._provider_runtime.execute_provider_strategy(
            request=request,
            workflow_id=workflow_id,
            media_type="video",
            generator=lambda attempt_request, provider: generate_storyboard_video_media_output(
                provider,
                attempt_request.input_context,
                provider_input_assets(input_assets, attempt_request.input_context),
                workflow_id,
                binding_plan,
            ),
        )
        return merge_prompt_optimization(
            media_output,
            optimization,
            request.node_type,
            workflow_id,
        )

    def _character_image_generation(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        _input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        provider = build_media_provider(self._settings)
        return provider.generate_character_turnaround_images(
            with_override_in_character_design(
                request.input_context["character_design"],
                request.override_prompt,
            ),
            workflow_id,
        )

    def _scene_image_generation(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        _input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        provider = build_media_provider(self._settings)
        return provider.generate_scene_reference_images(
            with_override_in_scene_design(
                request.input_context["scene_design"],
                request.override_prompt,
            ),
            workflow_id,
        )

    def _storyboard_image_generation(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        context = request.input_context
        provider = build_media_provider(self._settings)
        return provider.generate_storyboard_images(
            with_override_in_storyboard_scenes(
                storyboard_scenes(context),
                request.override_prompt,
            ),
            workflow_id,
            input_assets=input_assets,
            context={**context, "override_prompt": request.override_prompt},
        )

    def _final_composition(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        _input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        latest_segments = load_workflow_segments(self._settings.media_data_dir, workflow_id)
        if not latest_segments or not all(
            segment_is_ready(self._settings.media_data_dir, segment) for segment in latest_segments
        ):
            return final_composition_waiting_output(
                self._settings.media_data_dir,
                workflow_id,
                latest_segments,
                overwrite_ready=request.force_rerun,
            )
        try:
            return FinalCompositionTimelineService(self._settings).render_for_node_run(workflow_id)
        except FinalCompositionTimelineError as exc:
            detail = exc.detail
            return {
                "workflow_id": workflow_id,
                "asset_id": "final-ad-video",
                "status": "failed",
                "composition_status": "failed",
                "local_path": None,
                "public_url": None,
                "error": str(detail.get("message") or exc),
                "error_code": detail.get("code"),
                "output_assets": [],
                "assets": [],
            }

    def _binding_failure_output(
        self,
        binding_plan: dict[str, Any],
        optimization: dict[str, Any],
        node_type: str,
        workflow_id: str,
    ) -> dict[str, Any]:
        return merge_prompt_optimization(
            {
                **storyboard_binding_failure_output(binding_plan["error"]),
                "scene_assets": binding_plan.get("scene_assets", []),
                "character_assets": binding_plan.get("character_assets", []),
                "product_assets": binding_plan.get("product_assets", []),
                "shots": binding_plan.get("shots", []),
            },
            optimization,
            node_type,
            workflow_id,
        )
