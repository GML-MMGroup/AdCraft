"""Role-safe normalization for guided capability Materialization results."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import re

from pydantic import BaseModel, ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_materialization import (
    CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS,
    CapabilityMaterializationContextV1,
    MaterializationNormalizationV1,
)
from app.services.agent_canvas_guided_media_parameters import GuidedMediaParameterCompiler


MaterializationRepair = Callable[[tuple[str, ...]], Mapping[str, object] | BaseModel]
FallbackRenderer = Callable[[CapabilityIdV1, BaseModel], str | None]

_VIDEO_DIRECTIVE = re.compile(
    r"\b(?:(?:\d+(?:\.\d+)?|[a-z]+)[- ]?seconds?|camera move|animate|animation|"
    r"video (?:ad(?:vertisement)?|sequence)|shot sequence)\b",
    re.IGNORECASE,
)


class CapabilityMaterializationNormalizer:
    """Validate role coherence, repair once, then render a typed fallback."""

    def __init__(
        self,
        compiler: GuidedMediaParameterCompiler | None = None,
        fallback_renderer: FallbackRenderer | None = None,
    ) -> None:
        self._compiler = compiler or GuidedMediaParameterCompiler()
        self._fallback_renderer = fallback_renderer or _fallback_prompt

    def normalize(
        self,
        *,
        capability_id: CapabilityIdV1,
        result: BaseModel,
        context: CapabilityMaterializationContextV1 | None = None,
        repair: MaterializationRepair | None = None,
    ) -> MaterializationNormalizationV1:
        contract = CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS[capability_id]
        typed = contract.model_validate(result)
        violations = _violations(capability_id, typed)
        original_violations = violations
        mode = "model"
        warnings: tuple[str, ...] = ()
        if violations and repair is not None:
            try:
                repaired = contract.model_validate(repair(violations))
                repaired_violations = _violations(capability_id, repaired)
                if not repaired_violations:
                    typed = repaired
                    violations = ()
                    mode = "repaired"
                    warnings = original_violations
                else:
                    violations = repaired_violations
            except (ValidationError, TimeoutError, TypeError, ValueError):
                pass
        if violations:
            fallback = self._fallback_renderer(capability_id, typed)
            if fallback is None:
                raise V2PersistenceError(
                    "materialization_prompt_repair_failed",
                    "Materialization prompt could not be repaired from validated role content.",
                    stage="capability_materialization_normalization",
                )
            typed = typed.model_copy(update={"generation_prompt": fallback})
            mode = "deterministic_fallback"
            warnings = tuple(dict.fromkeys(violations))
        explicit_constraints = context.explicit_constraints if context is not None else {}
        creative_role = _creative_role(capability_id, typed)
        compiled = self._compiler.compile(
            capability_id=capability_id,
            creative_role=creative_role,
            structured_content=typed.structured_content,
            explicit_constraints=explicit_constraints,
        )
        return MaterializationNormalizationV1(
            result=typed,
            parameters=compiled.parameters,
            parameter_provenance=compiled.parameter_provenance,
            mode=mode,
            warnings=warnings,
        )


def _violations(capability_id: CapabilityIdV1, result: BaseModel) -> tuple[str, ...]:
    prompt = str(getattr(result, "generation_prompt", "") or "")
    if capability_id in {"product_design", "prop_design", "character_design"} and (
        _VIDEO_DIRECTIVE.search(prompt)
    ):
        return ("materialization_prompt_role_mismatch",)
    if capability_id == "scene_design" and _VIDEO_DIRECTIVE.search(prompt):
        return ("materialization_prompt_role_mismatch",)
    if capability_id == "storyboard_design" and "3x3" not in prompt.casefold():
        return ("materialization_prompt_role_mismatch",)
    return ()


def _fallback_prompt(capability_id: CapabilityIdV1, result: BaseModel) -> str | None:
    structured = result.structured_content
    style = getattr(structured, "style", None)
    style_prompt = str(getattr(style, "style_prompt", "") or "").strip()
    if capability_id in {"product_design", "prop_design", "character_design"}:
        identity = str(getattr(structured, "subject_identity", "") or "").strip()
        summary = str(getattr(structured, "design_summary", "") or "").strip()
        if not identity or not summary:
            return None
        return _join(
            f"Create one still advertising design image of {identity}.",
            summary,
            f"Visual style: {style_prompt}." if style_prompt else "",
            "Keep the subject identity and design details consistent.",
        )
    if capability_id == "scene_design":
        identity = str(getattr(structured, "scene_identity", "") or "").strip()
        summary = str(getattr(structured, "environment_summary", "") or "").strip()
        if not identity or not summary:
            return None
        return _join(
            f"Create one static 3x3 scene design board for {identity}.",
            summary,
            f"Layout: {getattr(structured, 'layout', '')}.",
            f"Lighting: {getattr(structured, 'lighting', '')}.",
            f"Visual style: {style_prompt}." if style_prompt else "",
        )
    if capability_id == "storyboard_design":
        panels = tuple(getattr(structured, "panels", ()))
        if len(panels) != 9:
            return None
        return _join(
            "Create one ordered 3x3 storyboard grid with exactly nine frames.",
            str(getattr(structured, "sequence_summary", "")),
            *(
                f"Frame {panel.panel_index}: {panel.beat}; {panel.composition}; "
                f"{panel.camera}; {panel.subject_action}."
                for panel in panels
            ),
            "Do not generate text in the image.",
        )
    if capability_id == "video_direction":
        return _join(
            str(getattr(structured, "segment_summary", "")),
            str(getattr(structured, "storyboard_content", "")),
            f"Dialogue: {getattr(structured, 'dialogue', '')}.",
            f"Environment sound: {getattr(structured, 'environment_sound', '')}.",
            f"Action effects: {getattr(structured, 'action_effects', '')}.",
        )
    if capability_id == "bgm_direction":
        return _join(
            str(getattr(structured, "music_summary", "")),
            f"Pace: {getattr(structured, 'pace', '')}.",
            f"Instrumentation: {getattr(structured, 'instrumentation', '')}.",
            "Instrumental only. No vocals.",
        )
    if capability_id == "quick_media":
        return str(getattr(structured, "content_summary", "") or "").strip() or None
    return None


def _creative_role(capability_id: CapabilityIdV1, result: BaseModel) -> str:
    if capability_id == "quick_media":
        return {
            "image": "general_image",
            "video": "general_video",
            "audio": "general_audio",
        }[result.structured_content.media_type]
    return {
        "world_setting": "world_setting",
        "product_design": "product",
        "prop_design": "prop",
        "character_design": "character",
        "scene_design": "scene",
        "script_authoring": "script",
        "storyboard_design": "storyboard_sequence",
        "video_direction": "storyboard_video",
        "bgm_direction": "bgm",
    }[capability_id]


def _join(*parts: str) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())
