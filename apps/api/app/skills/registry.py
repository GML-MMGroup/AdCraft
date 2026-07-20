from time import perf_counter
from typing import Any

from app.services.agent_trace import AgentTraceWriter, utc_now
from app.skills.loader import load_skill

CORE_AGENT_BY_NODE: dict[str, str] = {
    "director": "Director Agent",
    "script": "Script Writer Agent",
    "character-generation": "Character Designer Agent",
    "scene-generation": "Scene Designer Agent",
    "storyboard": "Storyboard Agent",
    "bgm": "BGM Agent",
    "storyboard-video-generation": "Video Generation / Composition Agent",
    "final-composition": "FFmpeg Composition Service",
    # Legacy orchestrator compatibility. These ids are not exposed in new graphs or catalog.
    "requirements-analysis": "Product Analyst Agent",
    "product-design": "Product Designer Agent",
    "creative-direction": "Creative Director Agent",
    "character-design": "Character Designer Agent",
    "scene-design": "Scene Designer Agent",
}

SKILL_IDS_BY_NODE: dict[str, tuple[str, ...]] = {
    "director": (
        "product_info_extraction",
        "selling_point_extraction",
        "audience_analysis",
        "campaign_appeal_generation",
        "creative_idea_generation",
    ),
    "script": (
        "creative_idea_generation",
        "short_ad_script_structure",
        "dialogue_copy_generation",
    ),
    "character-generation": (
        "character_spec_extraction",
        "character_prompt_expansion",
        "character_turnaround_prompt",
    ),
    "scene-generation": (
        "scene_spec_extraction",
        "pure_scene_prompt_expansion",
        "multi_view_scene_prompt",
    ),
    "storyboard": (
        "storyboard_beat_extraction",
        "storyboard_image_prompt_generation",
        "storyboard_video_prompt_generation",
        "visual_continuity_check",
    ),
    "bgm": (
        "bgm_prompt_generation",
        "mood_and_duration_matching",
    ),
    "storyboard-video-generation": (
        "segment_generation_planning",
        "reference_asset_selection",
    ),
    "final-composition": (),
    # Legacy orchestrator compatibility. These ids are not exposed in new graphs or catalog.
    "requirements-analysis": (
        "product_info_extraction",
        "selling_point_extraction",
        "audience_analysis",
        "campaign_appeal_generation",
    ),
    "product-design": (
        "product_info_extraction",
        "selling_point_extraction",
    ),
    "creative-direction": ("creative_idea_generation",),
    "character-design": (
        "character_spec_extraction",
        "character_prompt_expansion",
    ),
    "scene-design": (
        "scene_spec_extraction",
        "pure_scene_prompt_expansion",
        "multi_view_scene_prompt",
    ),
}


def augment_context_with_skills(
    *,
    node_id: str,
    core_agent_name: str | None,
    context: dict[str, Any],
    trace_writer: AgentTraceWriter,
    mock_mode: bool,
) -> dict[str, Any]:
    skill_outputs = record_skill_trace(
        node_id=node_id,
        core_agent_name=core_agent_name or CORE_AGENT_BY_NODE.get(node_id, node_id),
        context=context,
        trace_writer=trace_writer,
        mock_mode=mock_mode,
    )
    if not skill_outputs:
        return context
    return {**context, "skill_guidance": skill_outputs}


def record_skill_trace(
    *,
    node_id: str,
    core_agent_name: str,
    context: dict[str, Any],
    trace_writer: AgentTraceWriter,
    mock_mode: bool,
) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for skill_id in SKILL_IDS_BY_NODE.get(node_id, ()):
        started_at = utc_now()
        started_counter = perf_counter()
        error: str | None = None
        skill_name = skill_id
        source_path: str | None = None
        prompt = f"Skill load failed before prompt construction: {skill_id}"
        output: dict[str, Any]
        try:
            skill = load_skill(skill_id)
            skill_name = skill.name
            source_path = skill.source_path.as_posix()
            output = skill.apply(context)
            prompt = skill.build_prompt(context)
        except Exception as exc:  # noqa: BLE001 - trace skill errors before surfacing.
            error = f"{type(exc).__name__}: {exc}"
            output = {"summary": "Skill failed", "key_points": [], "prompt_notes": None}
        finished_at = utc_now()
        trace_writer.append(
            agent=core_agent_name,
            model=None,
            prompt=prompt,
            output=output,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=round((perf_counter() - started_counter) * 1000),
            metadata={
                "trace_role": "skill",
                "core_agent": core_agent_name,
                "skill_id": skill_id,
                "skill_name": skill_name,
                "skill_source_path": source_path,
                "node_id": node_id,
                "mode": "mock" if mock_mode else "real",
                "input_summary": output.get("key_points", []),
                "output_summary": output.get("summary"),
            },
        )
        if error is None:
            outputs[skill_id] = output
    return outputs


def record_mock_workflow_skill_trace(
    *,
    request: Any,
    trace_writer: AgentTraceWriter,
    skip_audio_agents: bool,
) -> None:
    request_context = (
        request.model_dump(mode="json") if hasattr(request, "model_dump") else dict(request)
    )
    contexts: dict[str, dict[str, Any]] = {
        "director": request_context,
        "script": {"requirements": request_context},
        "character-generation": {"requirements": request_context},
        "scene-generation": {"requirements": request_context},
        "storyboard": {"requirements": request_context},
        "storyboard-video-generation": {"requirements": request_context},
    }
    if not skip_audio_agents:
        contexts["bgm"] = {"requirements": request_context}
    for node_id, context in contexts.items():
        record_skill_trace(
            node_id=node_id,
            core_agent_name=CORE_AGENT_BY_NODE.get(node_id, node_id),
            context=context,
            trace_writer=trace_writer,
            mock_mode=True,
        )
