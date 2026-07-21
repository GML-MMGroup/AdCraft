import json
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any, TypeVar

from agno.agent import Agent
from agno.team import Team
from pydantic import BaseModel

from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.agent_outputs import (
    BgmOutput,
    CharacterDesignOutput,
    CreativeDirectionOutput,
    ProductDesignOutput,
    RequirementsAnalysisOutput,
    SceneDesignOutput,
    ScriptOutput,
    SoundEffectsOutput,
    StoryboardOutput,
    VoiceoverOutput,
)
from app.services.agent_trace import AgentTraceWriter, utc_now
from app.services.input_modality import (
    assets_for_prompt_target,
    classify_input_modality,
    selected_asset_summary,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text_with_warnings
from app.skills.registry import CORE_AGENT_BY_NODE, augment_context_with_skills
from app.tools.media import generate_subtitle_asset

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class AgentExecutionError(RuntimeError):
    """Raised when an LLM-backed agent cannot return validated structured output."""


def _members_by_name(team: Team) -> dict[str, Agent]:
    return {
        member.name: member
        for member in team.members
        if isinstance(member, Agent) and member.name is not None
    }


def _extract_json(content: Any) -> Any:
    if isinstance(content, BaseModel):
        return content.model_dump()
    if not isinstance(content, str):
        return content

    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = normalized.removeprefix("```json").removeprefix("```")
        normalized = normalized.removesuffix("```").strip()
    return json.loads(normalized)


def _run_agent(
    agent: Agent,
    output_model: type[OutputModel],
    task: str,
    context: dict[str, Any],
    trace_writer: AgentTraceWriter,
    node_id: str | None = None,
) -> OutputModel:
    try:
        sanitized_context, sanitizer_warnings = sanitize_context_for_llm_text_with_warnings(context)
    except Exception as exc:
        raise AgentExecutionError("Failed to sanitize agent context for LLM text.") from exc
    schema = output_model.model_json_schema()
    prompt = (
        f"{task}\n\n"
        "Return only valid JSON matching this JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "Input context:\n"
        f"{json.dumps(sanitized_context, ensure_ascii=False)}"
    )
    started_at = utc_now()
    started_counter = perf_counter()
    raw_output: Any = None
    try:
        response = agent.run(prompt)
        raw_output = response.content
        output = output_model.model_validate(_extract_json(raw_output))
        finished_at = utc_now()
        trace_writer.append(
            agent=agent.name or "Unnamed Agent",
            model=getattr(agent.model, "id", None),
            prompt=prompt,
            output=output.model_dump(),
            error=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=round((perf_counter() - started_counter) * 1000),
            metadata=_agent_trace_metadata(node_id, sanitizer_warnings),
        )
        return output
    except Exception as exc:
        finished_at = utc_now()
        trace_writer.append(
            agent=agent.name or "Unnamed Agent",
            model=getattr(agent.model, "id", None),
            prompt=prompt,
            output=raw_output,
            error=f"{type(exc).__name__}: {exc}",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=round((perf_counter() - started_counter) * 1000),
            metadata=_agent_trace_metadata(node_id, sanitizer_warnings),
        )
        raise AgentExecutionError(
            f"{agent.name} failed to return valid structured output."
        ) from exc


def _agent_trace_metadata(
    node_id: str | None,
    sanitizer_warnings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not node_id and not sanitizer_warnings:
        return None
    metadata: dict[str, Any] = {"trace_role": "main_agent"}
    if node_id:
        metadata["node_id"] = node_id
    if sanitizer_warnings:
        metadata["llm_context_warnings"] = sanitizer_warnings
    return metadata


def run_advertising_agents(
    request: AdWorkflowGenerateRequest,
    team: Team,
    trace_writer: AgentTraceWriter,
    skip_audio_agents: bool = False,
) -> dict[str, dict[str, Any]]:
    members = _members_by_name(team)
    request_context = {
        **request.model_dump(),
        "input_modality": classify_input_modality(request.selected_assets),
        "selected_assets": selected_asset_summary(request.selected_assets),
    }
    requirements_agent = members["Product Analyst Agent"]
    requirements = _run_agent(
        requirements_agent,
        RequirementsAnalysisOutput,
        "Analyze the advertising requirements.",
        augment_context_with_skills(
            node_id="requirements-analysis",
            core_agent_name=CORE_AGENT_BY_NODE["requirements-analysis"],
            context=request_context,
            trace_writer=trace_writer,
            mock_mode=False,
        ),
        trace_writer,
        "requirements-analysis",
    )
    product_design_agent = members["Product Designer Agent"]
    product_design_context = {
        "requirements": requirements.model_dump(),
        "channels": request.channels,
        "asset_prompt_context": assets_for_prompt_target(
            request.selected_assets,
            "product_design",
        ),
    }
    product_design = _run_agent(
        product_design_agent,
        ProductDesignOutput,
        "Create a commercial product showcase strategy.",
        augment_context_with_skills(
            node_id="product-design",
            core_agent_name=CORE_AGENT_BY_NODE["product-design"],
            context=product_design_context,
            trace_writer=trace_writer,
            mock_mode=False,
        ),
        trace_writer,
        "product-design",
    )
    creative_agent = members["Creative Director Agent"]
    creative_context = {
        "requirements": requirements.model_dump(),
        "product_design": product_design.model_dump(),
    }
    creative_direction = _run_agent(
        creative_agent,
        CreativeDirectionOutput,
        "Define a coordinated creative direction for the short advertisement.",
        augment_context_with_skills(
            node_id="creative-direction",
            core_agent_name=CORE_AGENT_BY_NODE["creative-direction"],
            context=creative_context,
            trace_writer=trace_writer,
            mock_mode=False,
        ),
        trace_writer,
        "creative-direction",
    )
    script_agent = members["Script Writer Agent"]
    script_context = {
        "requirements": requirements.model_dump(),
        "creative_direction": creative_direction.model_dump(),
    }
    script = _run_agent(
        script_agent,
        ScriptOutput,
        (
            "Write a short advertising script with a hook, product showcase, call to action, "
            "and 4-6 ordered shot_beats for the requested duration."
        ),
        augment_context_with_skills(
            node_id="script",
            core_agent_name=CORE_AGENT_BY_NODE["script"],
            context=script_context,
            trace_writer=trace_writer,
            mock_mode=False,
        ),
        trace_writer,
        "script",
    )
    with ThreadPoolExecutor(max_workers=3) as executor:
        character_agent = members["Character Designer Agent"]
        character_context = {
            "requirements": requirements.model_dump(),
            "creative_direction": creative_direction.model_dump(),
            "script": script.model_dump(),
            "asset_prompt_context": assets_for_prompt_target(
                request.selected_assets,
                "character_design",
            ),
        }
        character_future = executor.submit(
            _run_agent,
            character_agent,
            CharacterDesignOutput,
            "Design brand-aligned characters for the advertising short film.",
            augment_context_with_skills(
                node_id="character-design",
                core_agent_name=CORE_AGENT_BY_NODE["character-design"],
                context=character_context,
                trace_writer=trace_writer,
                mock_mode=False,
            ),
            trace_writer,
            "character-design",
        )
        scene_agent = members["Scene Designer Agent"]
        scene_context = {
            "requirements": requirements.model_dump(),
            "creative_direction": creative_direction.model_dump(),
            "script": script.model_dump(),
            "asset_prompt_context": assets_for_prompt_target(
                request.selected_assets,
                "scene_design",
            ),
        }
        scene_future = executor.submit(
            _run_agent,
            scene_agent,
            SceneDesignOutput,
            (
                "Design at least 3 distinct scene specs with stable scene_id values from the "
                "script shot_beats, unless the script explicitly uses one location."
            ),
            augment_context_with_skills(
                node_id="scene-design",
                core_agent_name=CORE_AGENT_BY_NODE["scene-design"],
                context=scene_context,
                trace_writer=trace_writer,
                mock_mode=False,
            ),
            trace_writer,
            "scene-design",
        )
        subtitle_future = executor.submit(
            generate_subtitle_asset,
            script.model_dump(),
            script.duration_seconds,
            trace_writer.workflow_id,
            trace_writer.data_dir,
        )
        character_design = character_future.result()
        scene_design = scene_future.result()
        subtitle_generation = subtitle_future.result()
    storyboard_agent = members["Storyboard Agent"]
    storyboard_context = {
        "requirements": requirements.model_dump(),
        "script": script.model_dump(),
        "characters": character_design.model_dump(),
        "scenes": scene_design.model_dump(),
    }
    storyboard = _run_agent(
        storyboard_agent,
        StoryboardOutput,
        (
            "Turn the script and visual designs into an ordered single-keyframe shot plan. "
            "Every scene must bind scene_id and input_asset_ids."
        ),
        augment_context_with_skills(
            node_id="storyboard",
            core_agent_name=CORE_AGENT_BY_NODE["storyboard"],
            context=storyboard_context,
            trace_writer=trace_writer,
            mock_mode=False,
        ),
        trace_writer,
        "storyboard",
    )
    outputs = {
        "requirements-analysis": requirements.model_dump(),
        "product-design": product_design.model_dump(),
        "creative-direction": creative_direction.model_dump(),
        "script": script.model_dump(),
        "subtitle-generation": subtitle_generation,
        "character-design": character_design.model_dump(),
        "scene-design": scene_design.model_dump(),
        "storyboard": storyboard.model_dump(),
    }
    if skip_audio_agents:
        return outputs

    with ThreadPoolExecutor(max_workers=3) as executor:
        sound_effects_future = executor.submit(
            _run_agent,
            members["Sound Effects Agent"],
            SoundEffectsOutput,
            "Plan only non-voice, non-music sound effects aligned to the storyboard.",
            {
                "requirements": requirements.model_dump(),
                "storyboard": storyboard.model_dump(),
                "scene_design": scene_design.model_dump(),
            },
            trace_writer,
            "sound-effects",
        )
        voiceover_future = executor.submit(
            _run_agent,
            members["Voiceover / Dubbing Agent"],
            VoiceoverOutput,
            "Plan only voiceover and dubbing tracks from the subtitle timing plan.",
            {
                "requirements": requirements.model_dump(),
                "script": script.model_dump(),
                "subtitle-generation": subtitle_generation,
                "character_design": character_design.model_dump(),
                "storyboard": storyboard.model_dump(),
            },
            trace_writer,
            "voiceover",
        )
        bgm_agent = members["BGM Agent"]
        bgm_context = {
            "requirements": requirements.model_dump(),
            "creative_direction": creative_direction.model_dump(),
            "script": script.model_dump(),
            "storyboard": storyboard.model_dump(),
            "channels": request.channels,
        }
        bgm_future = executor.submit(
            _run_agent,
            bgm_agent,
            BgmOutput,
            "Plan only full-ad background music with no voices or sound effects.",
            augment_context_with_skills(
                node_id="bgm",
                core_agent_name=CORE_AGENT_BY_NODE["bgm"],
                context=bgm_context,
                trace_writer=trace_writer,
                mock_mode=False,
            ),
            trace_writer,
            "bgm",
        )
        sound_effects = sound_effects_future.result()
        voiceover = voiceover_future.result()
        bgm = bgm_future.result()
    return {
        **outputs,
        "sound-effects": sound_effects.model_dump(),
        "voiceover": voiceover.model_dump(),
        "bgm": bgm.model_dump(),
    }
