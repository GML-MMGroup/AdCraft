from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2_storyboard_detail import (
    V2StoryboardCellPromptPlan,
    V2StoryboardDetailInput,
    V2StoryboardDetailPlan,
    V2StoryboardVideoDetailPlan,
    V2StoryboardVideoTimeSegment,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_storyboard_detail_quality import V2StoryboardDetailQualityService
from app.services.v2_high_risk_prompt_renderer import V2HighRiskPromptRenderer
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)
from app.services.v2_structured_llm import V2StructuredLLMClient, V2StructuredLLMError
from app.services.v2_versioning import V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION


class V2StoryboardDetailMaterializerError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.metadata = metadata or {}


class V2StoryboardDetailMaterializer:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        quality: V2StoryboardDetailQualityService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._quality = quality or V2StoryboardDetailQualityService()
        self._structured_llm = V2StructuredLLMClient(self._settings)
        self._structured_runtime = StructuredGenerationRuntime(
            settings=self._settings,
            structured_llm=self._structured_llm,
        )

    def materialize_detail(
        self,
        input_data: V2StoryboardDetailInput,
        *,
        force_mock: bool = False,
    ) -> V2StoryboardDetailPlan:
        if force_mock or self._settings.agno_mock_mode:
            plan = self._mock_plan(input_data)
            self._quality.validate_plan(plan, input_data=input_data)
            return plan
        return self._real_plan(input_data)

    def deterministic_fallback(
        self,
        input_data: V2StoryboardDetailInput,
        *,
        error_code: str,
        error_message: str,
    ) -> V2StoryboardDetailPlan:
        """Return a complete local contract when structured generation cannot recover."""
        plan = self._mock_plan(input_data)
        warning = {
            "code": "storyboard_detail_fallback_used",
            "message": "Storyboard detail preparation used the deterministic fallback.",
            "original_error_code": error_code,
            "original_error_message": error_message[:500],
        }
        return plan.model_copy(
            update={
                "materializer_mode": "fallback",
                "model_id": None,
                "quality_notes": [
                    *plan.quality_notes,
                    "storyboard_detail_fallback_used",
                ],
                "warnings": [*plan.warnings, warning],
            },
            deep=True,
        )

    def _real_plan(self, input_data: V2StoryboardDetailInput) -> V2StoryboardDetailPlan:
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise V2StoryboardDetailMaterializerError(
                "storyboard_detail_unavailable",
                "LLM API key and base URL are required for real storyboard detail materialization.",
            )
        try:
            spec = StructuredGenerationSpec[V2StoryboardDetailPlan](
                stage_name="storyboard_detail",
                contract_name="V2StoryboardDetailPlan",
                model_id=self._settings.llm_creative_model,
                system_prompt=_system_prompt(),
                input_payload=_materializer_payload(input_data),
                output_model=V2StoryboardDetailPlan,
                quality_validator=lambda output: self._quality.validate_plan(
                    output,
                    input_data=input_data,
                ),
                repair_context_builder=_storyboard_detail_repair_context,
                fallback_builder=lambda error: self._fallback_plan(input_data, error),
                trace_metadata={
                    "workflow_id": input_data.workflow_id,
                    "shot_id": input_data.shot_id,
                    "shot_index": input_data.shot_index,
                },
                temperature=0.35,
            )
            result = self._structured_runtime.run(spec)
        except StructuredGenerationRuntimeError as exc:
            code = _error_code(exc)
            raise V2StoryboardDetailMaterializerError(
                code,
                str(exc),
                metadata=_error_metadata(exc, input_data, code),
            ) from exc
        plan = _with_runtime_metadata(
            result.output,
            model_id=self._settings.llm_creative_model,
            mode=result.mode,
            warnings=result.warnings,
        )
        self._quality.validate_plan(plan, input_data=input_data)
        return plan

    def _fallback_plan(
        self,
        input_data: V2StoryboardDetailInput,
        error: V2StructuredLLMError,
    ) -> V2StoryboardDetailPlan:
        plan = self._mock_plan(input_data)
        warning = {
            "code": "storyboard_detail_fallback_used",
            "message": "Storyboard detail materializer used deterministic fallback after LLM validation failed.",
            "original_error_code": error.code,
            "original_error_message": str(error)[:500],
        }
        return plan.model_copy(
            update={
                "materializer_mode": "fallback",
                "model_id": None,
                "quality_notes": [
                    *plan.quality_notes,
                    "storyboard_detail_fallback_used",
                ],
                "warnings": [*plan.warnings, warning],
            },
            deep=True,
        )

    def _mock_plan(self, input_data: V2StoryboardDetailInput) -> V2StoryboardDetailPlan:
        product = _first_summary(input_data.product_brief_summaries, "the hero product")
        character = _first_summary(input_data.character_brief_summaries, "the lead character")
        scene = _first_summary(input_data.scene_brief_summaries, "the established scene")
        style = str(input_data.skill_context.get("style") or "premium commercial realism")
        lighting = _lighting_from_summary(scene)
        action = _shot_action(input_data)
        reference_asset_ids = _reference_asset_ids(input_data.selected_reference_summaries)
        duration = input_data.provider_duration_seconds
        time_segments = _time_segments(duration, action)
        narration = str(input_data.script_shot.get("narration") or "").strip()
        dialogue = (
            narration or "No spoken dialogue; communicate the beat through performance and action."
        )
        voice_style = (
            "Warm, clear, natural commercial line delivery."
            if narration
            else "No voice performance required; keep character reactions readable without speech."
        )
        cells = [
            _cell_prompt(
                input_data,
                slot_type="shot_cell_1",
                cell_index=1,
                cell_role="establishing",
                beat=(
                    "establishing frame with wide camera framing, clear scene and character blocking, "
                    "and the product visible before the action begins"
                ),
                product=product,
                character=character,
                scene=scene,
                style=style,
                lighting=lighting,
                action=action,
                reference_asset_ids=reference_asset_ids,
            ),
            _cell_prompt(
                input_data,
                slot_type="shot_cell_2",
                cell_index=2,
                cell_role="action",
                beat=(
                    "action frame with medium camera framing, character interaction, "
                    "and the product movement starting"
                ),
                product=product,
                character=character,
                scene=scene,
                style=style,
                lighting=lighting,
                action=action,
                reference_asset_ids=reference_asset_ids,
            ),
            _cell_prompt(
                input_data,
                slot_type="shot_cell_3",
                cell_index=3,
                cell_role="detail",
                beat=(
                    "detail frame with close camera framing, strongest product interaction, "
                    "specific product or character detail focus, heightened emotion, and visual emphasis"
                ),
                product=product,
                character=character,
                scene=scene,
                style=style,
                lighting=lighting,
                action=action,
                reference_asset_ids=reference_asset_ids,
            ),
            _cell_prompt(
                input_data,
                slot_type="shot_cell_4",
                cell_index=4,
                cell_role="payoff",
                beat=(
                    "payoff transition frame with hero camera framing, resolved emotion, "
                    "and a clean product-readable ending"
                ),
                product=product,
                character=character,
                scene=scene,
                style=style,
                lighting=lighting,
                action=action,
                reference_asset_ids=reference_asset_ids,
            ),
        ]
        storyboard_content = _storyboard_content(time_segments, cells)
        audio_description = (
            "Production sound only: natural movement, product interaction, room tone, and tactile action cues; "
            "no background track or sung elements."
        )
        video_negative_constraints = (
            "No watermark. No subtitles. No distorted product labels. No identity drift. "
            "No static pan-only motion."
        )
        video_detail = V2StoryboardVideoDetailPlan(
            provider_prompt=(
                f"Create one {duration} second video segment for shot {input_data.shot_id}. "
                f"Use the four continuous keyframes as visual progression: {action}. Preserve {product}, "
                f"{character}, {scene}, {style}, {lighting}, and product-safe label continuity."
            ),
            storyboard_content=storyboard_content,
            dialogue=dialogue,
            audio_description=audio_description,
            voice_style=voice_style,
            video_negative_constraints=video_negative_constraints,
            time_segments=time_segments,
            desired_duration_seconds=input_data.desired_duration_seconds,
            provider_duration_seconds=duration,
            required_shot_cell_slot_ids=[
                f"{input_data.shot_id}:shot_cell_{index}" for index in range(1, 5)
            ],
            required_shot_cell_asset_ids=[],
        )
        return V2StoryboardDetailPlan(
            shot_id=input_data.shot_id,
            shot_index=input_data.shot_index,
            shot_summary_prompt=input_data.shot_summary_prompt,
            provider_duration_seconds=duration,
            desired_duration_seconds=input_data.desired_duration_seconds,
            cell_prompts=cells,
            video_detail=video_detail,
            reference_item_ids=_reference_item_ids(input_data),
            reference_asset_ids=reference_asset_ids,
            materializer_mode="mock",
            model_id=None,
            materializer_version=V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION,
            quality_notes=[
                "deterministic_storyboard_detail",
                "four_cell_progression",
                "timeline_video_detail",
            ],
            warnings=[],
        )


def _cell_prompt(
    input_data: V2StoryboardDetailInput,
    *,
    slot_type: str,
    cell_index: int,
    cell_role: str,
    beat: str,
    product: str,
    character: str,
    scene: str,
    style: str,
    lighting: str,
    action: str,
    reference_asset_ids: list[str],
) -> V2StoryboardCellPromptPlan:
    prompt = (
        f"{cell_role.replace('_', ' ').title()} full-frame keyframe for {input_data.shot_id}: "
        f"{beat}. Preserve same product identity ({product}), same character identity ({character}), "
        f"same scene identity ({scene}), same visual style ({style}), {lighting}, time of day continuity, "
        f"and shot action: {action}. Generate exactly one standalone full-frame image, with camera framing, "
        "blocking, emotion, product interaction, and visual emphasis appropriate to this beat."
    )
    return V2StoryboardCellPromptPlan(
        slot_type=slot_type,  # type: ignore[arg-type]
        cell_index=cell_index,  # type: ignore[arg-type]
        cell_role=cell_role,  # type: ignore[arg-type]
        provider_prompt=prompt,
        negative_prompt="No panel layout, no text overlays, no captions, no subtitles.",
        negative_constraints=[
            "No storyboard sheet",
            "No collage",
            "No split screen",
            "No multi-panel image",
            "No contact sheet",
            "No text labels",
            "No captions",
            "No subtitles",
            "No grid generation",
        ],
        continuity_notes=(
            "Maintain product, character, scene, style, lighting, time of day, and same-shot continuity."
        ),
        required_reference_asset_ids=reference_asset_ids,
    )


def _time_segments(duration: int, action: str) -> list[V2StoryboardVideoTimeSegment]:
    if duration == 10:
        boundaries = [(0.0, 2.5), (2.5, 5.0), (5.0, 7.5), (7.5, 10.0)]
    else:
        boundaries = [(0.0, 1.2), (1.2, 2.5), (2.5, 3.8), (3.8, 5.0)]
    labels = [
        "wide camera establishes the setting and product before action",
        "medium camera shows character interaction and action progression",
        "close camera emphasizes product interaction and detail focus",
        "hero camera resolves the action with a clean transition payoff",
    ]
    return [
        V2StoryboardVideoTimeSegment(
            start_seconds=start,
            end_seconds=end,
            content=f"{label}: {action}.",
        )
        for (start, end), label in zip(boundaries, labels, strict=True)
    ]


def _storyboard_content(
    time_segments: list[V2StoryboardVideoTimeSegment],
    cells: list[V2StoryboardCellPromptPlan],
) -> str:
    parts: list[str] = []
    for segment, cell in zip(time_segments, cells, strict=True):
        parts.append(
            f"{segment.start_seconds:.1f}-{segment.end_seconds:.1f}s: {segment.content} "
            f"Visual progression follows the {cell.cell_role.replace('_', ' ')} keyframe with camera continuity."
        )
    return " ".join(parts)


def _materializer_payload(input_data: V2StoryboardDetailInput) -> dict[str, Any]:
    return sanitize_context_for_llm_text(
        {
            "task": "Create four professional same-shot storyboard cell prompts and one timeline video detail prompt.",
            "input": input_data.model_dump(mode="json"),
            "output_contract": "V2StoryboardDetailPlan",
            "requirements": {
                "exactly_four_cell_prompts": [
                    "shot_cell_1",
                    "shot_cell_2",
                    "shot_cell_3",
                    "shot_cell_4",
                ],
                "cell_roles": ["establishing", "action", "detail", "payoff"],
                "video_provider_duration_seconds": [5, 10],
                "no_media_generation": True,
                "no_provider_tasks": True,
                "no_bgm_or_music_in_video_detail": True,
                "no_base64_data_urls_raw_bytes_local_file_content_or_secrets": True,
            },
        }
    )


def _system_prompt() -> str:
    return (
        V2HighRiskPromptRenderer()
        .render(
            prompt_id="v2.storyboard.detail.v1",
            context={},
            identity={"path_kind": "normal"},
        )
        .prompt_text
    )


def _with_runtime_metadata(
    plan: V2StoryboardDetailPlan,
    *,
    model_id: str | None,
    mode: str,
    warnings: list[dict[str, Any]],
) -> V2StoryboardDetailPlan:
    materializer_mode = "fallback" if mode == "fallback" else "real"
    quality_notes = list(plan.quality_notes)
    if mode == "repair":
        quality_notes.append("storyboard_detail_output_repaired")
    if mode == "fallback":
        quality_notes.append("storyboard_detail_fallback_used")
    return plan.model_copy(
        update={
            "materializer_mode": materializer_mode,
            "model_id": None if materializer_mode == "fallback" else model_id,
            "materializer_version": V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION,
            "quality_notes": list(dict.fromkeys(quality_notes)),
            "warnings": _dedupe_warnings([*plan.warnings, *warnings]),
        },
        deep=True,
    )


def _storyboard_detail_repair_context(error: V2StructuredLLMError) -> dict[str, Any]:
    details = error.quality_error_details
    if isinstance(details, dict):
        return dict(details)
    return {}


def _dedupe_warnings(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for warning in values:
        key = repr(sorted(warning.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def _error_code(exc: StructuredGenerationRuntimeError) -> str:
    if _namespace_quality_error(exc.trace_metadata) is not None:
        return "v2_storyboard_namespace_violation"
    if exc.code == "structured_generation_unavailable":
        return "storyboard_detail_unavailable"
    if exc.code == "structured_generation_fallback_failed":
        return "v2_storyboard_fallback_failed"
    if exc.code == "structured_generation_repair_failed":
        return "storyboard_detail_repair_failed"
    if exc.code == "structured_generation_schema_failed":
        return "storyboard_detail_repair_failed"
    if exc.code == "structured_generation_quality_failed":
        return "storyboard_detail_repair_failed"
    if exc.code == "structured_llm_call_failed":
        return "storyboard_detail_llm_call_failed"
    return "storyboard_detail_llm_call_failed"


def _error_metadata(
    exc: StructuredGenerationRuntimeError,
    input_data: V2StoryboardDetailInput,
    code: str,
) -> dict[str, Any]:
    namespace_error = _namespace_quality_error(exc.trace_metadata)
    if code == "v2_storyboard_namespace_violation" and namespace_error is not None:
        details = namespace_error.get("details")
        details = details if isinstance(details, dict) else {}
        return sanitize_context_for_llm_text(
            {
                "stage": "storyboard_detail_quality",
                "node_id": "storyboard",
                "item_id": input_data.shot_id,
                "shot_id": input_data.shot_id,
                "slot_id": f"{input_data.shot_id}:shot_cell_1",
                "slot_type": "shot_cell_1",
                "error_code": code,
                "failure_codes": details.get("failure_codes", []),
                "violations": details.get("violations", []),
            }
        )
    metadata = {
        "stage": "storyboard_detail_materialization",
        "node_id": "storyboard",
        "item_id": input_data.shot_id,
        "slot_id": f"{input_data.shot_id}:shot_cell_1",
        "slot_type": "shot_cell_1",
        "error_code": code,
        "original_error_code": exc.code,
        "trace_metadata": sanitize_context_for_llm_text(exc.trace_metadata),
    }
    return sanitize_context_for_llm_text(metadata)


def _namespace_quality_error(trace_metadata: dict[str, Any]) -> dict[str, Any] | None:
    quality_errors = trace_metadata.get("quality_errors")
    if not isinstance(quality_errors, list):
        return None
    return next(
        (
            error
            for error in quality_errors
            if isinstance(error, dict) and error.get("code") == "v2_storyboard_namespace_violation"
        ),
        None,
    )


def _first_summary(items: list[dict[str, Any]], fallback: str) -> str:
    if not items:
        return fallback
    item = items[0]
    value = item.get("summary") or item.get("description") or item.get("display_name")
    return str(value).strip() or fallback


def _lighting_from_summary(scene_summary: str) -> str:
    lower = scene_summary.lower()
    if "night" in lower:
        return "night lighting"
    if "morning" in lower:
        return "morning lighting"
    if "evening" in lower:
        return "evening lighting"
    if "afternoon" in lower:
        return "afternoon lighting"
    if "sunlit" in lower:
        return "sunlit lighting"
    return "consistent commercial lighting"


def _shot_action(input_data: V2StoryboardDetailInput) -> str:
    if input_data.shot_summary_prompt:
        return input_data.shot_summary_prompt
    for key in ("visual_prompt", "description"):
        value = input_data.script_shot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return input_data.shot_summary_prompt


def _reference_asset_ids(selected_references: list[dict[str, Any]]) -> list[str]:
    ids = [
        str(reference.get("asset_id") or "").strip()
        for reference in selected_references
        if str(reference.get("asset_id") or "").strip()
    ]
    return list(dict.fromkeys(ids))


def _reference_item_ids(input_data: V2StoryboardDetailInput) -> list[str]:
    item_ids = [
        str(reference.get("owner_item_id") or "").strip()
        for reference in input_data.selected_reference_summaries
        if str(reference.get("owner_item_id") or "").strip()
    ]
    if item_ids:
        return list(dict.fromkeys(item_ids))
    derived = []
    for collection in (
        input_data.product_brief_summaries,
        input_data.character_brief_summaries,
        input_data.scene_brief_summaries,
    ):
        derived.extend(
            str(item.get("item_id") or "").strip()
            for item in collection
            if str(item.get("item_id") or "").strip()
        )
    return list(dict.fromkeys(derived))
