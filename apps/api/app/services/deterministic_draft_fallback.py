"""Role-specific deterministic Draft fallback after selected-option failure."""

from __future__ import annotations

from collections.abc import Callable

from app.schemas.agent_canvas_ad_media import (
    BgmContentV2,
    DesignAssetContentV2,
    SceneBoardPanelV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    StoryboardPanelV2,
    VideoSegmentContentV2,
    VisualStyleContractV2,
)
from app.schemas.agent_canvas_creative_session import (
    BgmAudioSpecialistDraftV2,
    CharacterImageSpecialistDraftV2,
    ProductImageSpecialistDraftV2,
    PropImageSpecialistDraftV2,
    SceneImageSpecialistDraftV2,
    SpecialistDraftV2,
    StoryboardImageSpecialistDraftV2,
    VideoSpecialistDraftV2,
)
from app.schemas.agent_canvas_world_setting import WorldSettingMaterializationDraftV2
from app.schemas.agent_operation_recovery import (
    DeterministicDraftFallbackRequestV2,
    DeterministicDraftFallbackResultV2,
)
from app.schemas.agent_working_documents import (
    StoryboardNarrativeSegmentV2,
    StoryboardPlanGlobalParametersV2,
    StoryboardPlanRowV2,
)
from app.services.v2_prompt_registry import V2PromptRegistry


_ALLOWED_KINDS = {
    "world_setting",
    "product",
    "prop",
    "character",
    "scene",
    "storyboard",
    "video",
    "bgm",
}
_ALLOWED_FAILURE_CODES = {
    "agent_deadline_exceeded",
    "agent_structured_output_invalid",
    "specialist_contract_failed",
    "specialist_draft_invalid",
}


class DeterministicDraftFallbackServiceV2:
    def __init__(self, *, prompt_registry: V2PromptRegistry | None = None) -> None:
        self._prompt_registry = prompt_registry or V2PromptRegistry()

    def evaluate(
        self,
        request: DeterministicDraftFallbackRequestV2,
    ) -> DeterministicDraftFallbackResultV2 | None:
        if not self._eligible(request):
            return None
        self._record_prompt_lineage(request)
        if request.proposal_kind == "world_setting":
            return DeterministicDraftFallbackResultV2(
                operation_policy_id=request.operation_policy_id,
                world_setting=self._world_setting(request),
            )
        builder: Callable[[DeterministicDraftFallbackRequestV2], SpecialistDraftV2] = {
            "product": self._product,
            "prop": self._prop,
            "character": self._character,
            "scene": self._scene,
            "storyboard": self._storyboard,
            "video": self._video,
            "bgm": self._bgm,
        }[request.proposal_kind]
        return DeterministicDraftFallbackResultV2(
            operation_policy_id=request.operation_policy_id,
            draft=builder(request),
        )

    @staticmethod
    def _eligible(request: DeterministicDraftFallbackRequestV2) -> bool:
        if request.proposal_kind not in _ALLOWED_KINDS:
            return False
        if request.failure.failure_stage != "materialization":
            return False
        if request.failure.code not in _ALLOWED_FAILURE_CODES:
            return False
        if not request.safety_approved or not request.model_capability_valid:
            return False
        if request.provider_started:
            return False
        if request.current_workflow_revision != request.expected_workflow_revision:
            return False
        if request.current_session_revision != request.expected_session_revision:
            return False
        if not request.context.selected_option_draft_prompt.strip():
            return False
        if request.proposal_kind in {"storyboard", "video", "bgm"}:
            try:
                _storyboard_excerpt(request)
            except (TypeError, ValueError):
                return False
        accepted_ids = {item.source_id for item in request.accepted_references}
        return set(request.required_reference_ids).issubset(accepted_ids)

    def _record_prompt_lineage(self, request: DeterministicDraftFallbackRequestV2) -> None:
        self._prompt_registry.render_result_for_prompt_id(
            prompt_id="v2.fallback.deterministic_generation.v1",
            rendered_prompt=request.context.selected_option_draft_prompt,
            render_context={
                "proposal_kind": request.proposal_kind,
                "selected_option_id": request.selected_option_id,
                "reference_ids": [item.source_id for item in request.accepted_references],
            },
            workflow_id=request.context.workflow_id,
            specialist=request.context.specialist_name,
            path_kind="deterministic_fallback",
        )

    @staticmethod
    def _style() -> VisualStyleContractV2:
        return VisualStyleContractV2(
            style_prompt="Detailed semi-realistic advertising illustration",
            source="platform_default",
        )

    @staticmethod
    def _base(request: DeterministicDraftFallbackRequestV2) -> dict[str, object]:
        return {
            "title": f"{request.proposal_kind.replace('_', ' ').title()} Draft",
            "summary_prompt": request.context.selected_option_summary,
            "generation_prompt": request.context.selected_option_draft_prompt,
            "parameters": {
                "materialization_mode": "deterministic_fallback",
                "warning_code": "specialist_materialization_fallback",
                "operation_policy_id": request.operation_policy_id,
            },
            "reference_intents": request.accepted_references,
            "warnings": ("specialist_materialization_fallback",),
        }

    def _product(self, request: DeterministicDraftFallbackRequestV2) -> SpecialistDraftV2:
        return self._as_generic(
            ProductImageSpecialistDraftV2(
                **self._base(request),
                node_type="image",
                creative_role="product",
                structured_content=DesignAssetContentV2(
                    subject_identity=request.context.selected_option_summary,
                    design_summary=request.context.selected_option_draft_prompt,
                    style=self._style(),
                ),
            )
        )

    def _prop(self, request: DeterministicDraftFallbackRequestV2) -> SpecialistDraftV2:
        return self._as_generic(
            PropImageSpecialistDraftV2(
                **self._base(request),
                node_type="image",
                creative_role="prop",
                structured_content=DesignAssetContentV2(
                    subject_identity=request.context.selected_option_summary,
                    design_summary=request.context.selected_option_draft_prompt,
                    style=self._style(),
                ),
            )
        )

    def _character(self, request: DeterministicDraftFallbackRequestV2) -> SpecialistDraftV2:
        return self._as_generic(
            CharacterImageSpecialistDraftV2(
                **self._base(request),
                node_type="image",
                creative_role="character",
                structured_content=DesignAssetContentV2(
                    subject_identity=request.context.selected_option_summary,
                    design_summary=request.context.selected_option_draft_prompt,
                    style=self._style(),
                ),
            )
        )

    def _scene(self, request: DeterministicDraftFallbackRequestV2) -> SpecialistDraftV2:
        summary = request.context.selected_option_summary
        return self._as_generic(
            SceneImageSpecialistDraftV2(
                **self._base(request),
                node_type="image",
                creative_role="scene",
                structured_content=SceneDesignBoardContentV2(
                    scene_identity=summary,
                    environment_summary=request.context.selected_option_draft_prompt,
                    layout="A coherent advertising environment with stable spatial anchors.",
                    lighting="Consistent commercial lighting.",
                    materials="Consistent materials across every view.",
                    time_of_day="Day",
                    style=self._style(),
                    panels=tuple(
                        SceneBoardPanelV2(
                            panel_index=index,
                            view_or_zone=f"Spatial view {index}",
                            spatial_description=f"{summary} from spatial view {index}.",
                            lighting_material_detail=(
                                f"Preserve lighting and materials for spatial view {index}."
                            ),
                        )
                        for index in range(1, 10)
                    ),
                ),
            )
        )

    def _storyboard(self, request: DeterministicDraftFallbackRequestV2) -> SpecialistDraftV2:
        _, segment, rows = _storyboard_excerpt(request)
        return self._as_generic(
            StoryboardImageSpecialistDraftV2(
                **self._base(request),
                node_type="image",
                creative_role="storyboard_sequence",
                structured_content=StoryboardGridContentV2(
                    sequence_summary=segment.narrative_goal,
                    narrative_goal=segment.narrative_goal,
                    style=self._style(),
                    panels=tuple(
                        StoryboardPanelV2(
                            panel_index=row.panel_index,
                            beat=row.content_beat,
                            composition=row.content_beat,
                            camera=row.camera_description,
                            subject_action=row.content_beat,
                            continuity_from_previous=(
                                segment.start_state
                                if row.panel_index == 1
                                else f"Continue from panel {row.panel_index - 1}"
                            ),
                        )
                        for row in rows
                    ),
                ),
            )
        )

    def _video(self, request: DeterministicDraftFallbackRequestV2) -> SpecialistDraftV2:
        global_parameters, segment, _ = _storyboard_excerpt(request)
        duration = segment.end_seconds - segment.start_seconds
        typed_parameters = {
            "duration_seconds": duration,
            "aspect_ratio": global_parameters.aspect_ratio,
        }
        base = self._base(request)
        base["parameters"] = {**dict(base["parameters"]), **typed_parameters}
        return self._as_generic(
            VideoSpecialistDraftV2(
                **base,
                node_type="video",
                creative_role="storyboard_video",
                structured_content=VideoSegmentContentV2(
                    segment_summary=segment.narrative_goal,
                    duration_seconds=duration,
                    storyboard_content=(
                        f"{segment.start_state} -> {segment.end_state}. {segment.narrative_goal}"
                    ),
                ),
            )
        )

    def _bgm(self, request: DeterministicDraftFallbackRequestV2) -> SpecialistDraftV2:
        global_parameters, _, _ = _storyboard_excerpt(request)
        duration = global_parameters.total_duration_seconds
        typed_parameters = {"duration_seconds": duration}
        base = self._base(request)
        base["parameters"] = {**dict(base["parameters"]), **typed_parameters}
        return self._as_generic(
            BgmAudioSpecialistDraftV2(
                **base,
                node_type="audio",
                creative_role="bgm",
                structured_content=BgmContentV2(
                    music_summary=request.context.selected_option_summary,
                    duration_seconds=duration,
                    pace="Medium",
                    energy_curve="Build and resolve",
                    instrumentation="Instrumental ensemble",
                    mood="Confident",
                ),
            )
        )

    @staticmethod
    def _world_setting(
        request: DeterministicDraftFallbackRequestV2,
    ) -> WorldSettingMaterializationDraftV2:
        return WorldSettingMaterializationDraftV2(
            title="World Setting",
            document_content=(
                f"{request.context.selected_option_summary}\n\n"
                f"{request.context.selected_option_draft_prompt}"
            ),
        )

    @staticmethod
    def _as_generic(draft: object) -> SpecialistDraftV2:
        return SpecialistDraftV2.model_validate(draft.model_dump(mode="json"))


def _storyboard_excerpt(
    request: DeterministicDraftFallbackRequestV2,
) -> tuple[
    StoryboardPlanGlobalParametersV2,
    StoryboardNarrativeSegmentV2,
    tuple[StoryboardPlanRowV2, ...],
]:
    excerpt = request.context.agent_document_context
    if excerpt is None or excerpt.document_kind != "storyboard_production_plan":
        raise ValueError("Storyboard fallback requires a production-plan excerpt.")
    content = excerpt.content
    global_parameters = StoryboardPlanGlobalParametersV2.model_validate(
        content.get("global_parameters")
    )
    segments = tuple(
        StoryboardNarrativeSegmentV2.model_validate(item) for item in content.get("segments", ())
    )
    rows = tuple(StoryboardPlanRowV2.model_validate(item) for item in content.get("rows", ()))
    if len(segments) != 1 or len(rows) != 9:
        raise ValueError("Storyboard fallback requires one sequence and nine rows.")
    segment = segments[0]
    if any(row.sequence_id != segment.sequence_id for row in rows):
        raise ValueError("Storyboard fallback rows must belong to the selected sequence.")
    if tuple(row.panel_index for row in rows) != tuple(range(1, 10)):
        raise ValueError("Storyboard fallback rows must retain panel order.")
    return global_parameters, segment, rows
