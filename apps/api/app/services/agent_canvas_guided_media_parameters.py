"""Compile guided media authoring parameters with durable provenance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, JsonValue

from app.schemas.agent_canvas_video_parameters import CanvasParameterProvenanceV2
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.services.provider_model_catalog import GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO


_IMAGE_SIZE_BY_RATIO = GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO


@dataclass(frozen=True, slots=True)
class GuidedMediaParameterCompilation:
    parameters: dict[str, JsonValue]
    parameter_provenance: dict[str, CanvasParameterProvenanceV2]


class GuidedMediaParameterCompiler:
    """Apply explicit, structured, then role-default parameter precedence."""

    def compile(
        self,
        *,
        capability_id: CapabilityIdV1,
        creative_role: str,
        structured_content: BaseModel,
        explicit_constraints: dict[str, object],
    ) -> GuidedMediaParameterCompilation:
        if capability_id in {"scene_design", "storyboard_design"}:
            return self._compile_guided_image(
                creative_role=creative_role,
                explicit_constraints=explicit_constraints,
            )
        if capability_id in {"product_design", "prop_design", "character_design"}:
            return self._compile_design_image(explicit_constraints)
        if capability_id == "video_direction":
            return self._compile_video(structured_content, explicit_constraints)
        if capability_id == "bgm_direction":
            return self._compile_bgm(structured_content, explicit_constraints)
        return GuidedMediaParameterCompilation(parameters={}, parameter_provenance={})

    def _compile_guided_image(
        self,
        *,
        creative_role: str,
        explicit_constraints: dict[str, object],
    ) -> GuidedMediaParameterCompilation:
        ratio = _constraint(explicit_constraints, "aspect_ratio") or "1:1"
        if not isinstance(ratio, str) or ratio not in _IMAGE_SIZE_BY_RATIO:
            ratio = "1:1"
        origin = (
            "user_explicit"
            if _constraint(explicit_constraints, "aspect_ratio")
            else ("guidance_default")
        )
        size = _IMAGE_SIZE_BY_RATIO[ratio]
        return GuidedMediaParameterCompilation(
            parameters={"aspect_ratio": ratio, "size": size},
            parameter_provenance={
                "aspect_ratio": _provenance(origin, ratio, ratio),
                "size": _provenance(
                    "guidance_default" if origin == "user_explicit" else origin,
                    size,
                    size,
                ),
            },
        )

    def _compile_design_image(
        self,
        explicit_constraints: dict[str, object],
    ) -> GuidedMediaParameterCompilation:
        scoped = explicit_constraints.get("design_asset_parameters")
        scoped_constraints = scoped if isinstance(scoped, dict) else {}
        ratio = scoped_constraints.get("aspect_ratio")
        if isinstance(ratio, str) and ratio in _IMAGE_SIZE_BY_RATIO:
            size = _IMAGE_SIZE_BY_RATIO[ratio]
            return GuidedMediaParameterCompilation(
                parameters={"aspect_ratio": ratio, "size": size},
                parameter_provenance={
                    "aspect_ratio": _provenance("user_explicit", ratio, ratio),
                    "size": _provenance("guidance_default", size, size),
                },
            )
        size = _IMAGE_SIZE_BY_RATIO["1:1"]
        return GuidedMediaParameterCompilation(
            parameters={"aspect_ratio": "1:1", "size": size},
            parameter_provenance={
                "aspect_ratio": _provenance("role_default", "1:1", "1:1"),
                "size": _provenance("role_default", size, size),
            },
        )

    def _compile_video(
        self,
        structured_content: BaseModel,
        explicit_constraints: dict[str, object],
    ) -> GuidedMediaParameterCompilation:
        parameters: dict[str, JsonValue] = {}
        provenance: dict[str, CanvasParameterProvenanceV2] = {}
        structured_duration = getattr(structured_content, "duration_seconds", 5)
        requested_duration = _constraint(explicit_constraints, "duration_seconds")
        duration_origin = "user_explicit"
        if not _positive_number(requested_duration):
            requested_duration = structured_duration
            duration_origin = "structured_content"
        duration = min(float(requested_duration), 15.0)
        if duration.is_integer():
            duration = int(duration)
        parameters["duration_seconds"] = duration
        provenance["duration_seconds"] = _provenance(
            duration_origin,
            requested_duration,
            duration,
            normalization_code=(
                "duration_clamped_to_maximum" if float(requested_duration) > 15 else None
            ),
        )
        for field in ("aspect_ratio", "resolution"):
            value = _constraint(explicit_constraints, field)
            if isinstance(value, str) and value.strip():
                normalized = value.strip()
                parameters[field] = normalized
                provenance[field] = _provenance(
                    "user_explicit",
                    normalized,
                    normalized,
                )
        generate_audio, audio_provenance = resolve_video_audio_parameter(
            structured_values=structured_content,
            explicit_constraints=explicit_constraints,
        )
        if generate_audio is not None and audio_provenance is not None:
            parameters["generate_audio"] = generate_audio
            provenance["generate_audio"] = _provenance(
                audio_provenance.origin,
                generate_audio,
                generate_audio,
            )
        return GuidedMediaParameterCompilation(parameters, provenance)

    def _compile_bgm(
        self,
        structured_content: BaseModel,
        explicit_constraints: dict[str, object],
    ) -> GuidedMediaParameterCompilation:
        requested = _constraint(explicit_constraints, "duration_seconds")
        origin = "user_explicit"
        if not _positive_number(requested):
            requested = getattr(structured_content, "duration_seconds", 30)
            origin = "structured_content"
        duration: int | float = float(requested)
        if duration.is_integer():
            duration = int(duration)
        return GuidedMediaParameterCompilation(
            parameters={"duration_seconds": duration},
            parameter_provenance={
                "duration_seconds": _provenance(origin, requested, duration),
            },
        )


def resolve_video_audio_parameter(
    *,
    structured_values: BaseModel | Mapping[str, object],
    explicit_constraints: Mapping[str, object],
) -> tuple[bool | None, CanvasParameterProvenanceV2 | None]:
    """Resolve native-audio intent for every V2 Video preparation path."""

    explicit_audio = _constraint(explicit_constraints, "generate_audio")
    audio_mode = _constraint(explicit_constraints, "audio_mode")
    silent_video = _constraint(explicit_constraints, "silent_video") is True
    if audio_mode == "none":
        value, origin = False, "user_explicit"
    elif isinstance(explicit_audio, bool):
        value, origin = explicit_audio, "user_explicit"
    elif silent_video:
        value, origin = False, "user_explicit"
    elif audio_mode == "full":
        value, origin = True, "user_explicit"
    else:
        sound_fields = (
            _structured_value(structured_values, "dialogue"),
            _structured_value(structured_values, "environment_sound"),
            _structured_value(structured_values, "action_effects"),
        )
        if not any(str(value).strip() for value in sound_fields):
            return None, None
        value, origin = True, "structured_content"
    return value, _provenance(origin, value, value)


def _constraint(constraints: Mapping[str, object], field: str) -> object | None:
    nested_keys = {
        "duration_seconds": ("required_video_parameters", "bgm_parameters"),
        "aspect_ratio": ("required_video_parameters", "required_image_parameters"),
        "resolution": ("required_video_parameters", "required_image_parameters"),
        "generate_audio": ("required_video_parameters",),
        "silent_video": ("required_video_parameters",),
        "audio_mode": ("required_video_parameters",),
    }
    if field in constraints:
        return constraints[field]
    for key in nested_keys.get(field, ()):
        nested = constraints.get(key)
        if isinstance(nested, dict) and field in nested:
            return nested[field]
    return None


def _structured_value(
    structured_values: BaseModel | Mapping[str, object],
    field: str,
) -> object:
    if isinstance(structured_values, Mapping):
        return structured_values.get(field, "")
    return getattr(structured_values, field, "")


def _positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _provenance(
    origin: str,
    requested_value: object,
    effective_value: object,
    *,
    normalization_code: str | None = None,
) -> CanvasParameterProvenanceV2:
    return CanvasParameterProvenanceV2.model_validate(
        {
            "origin": origin,
            "requested_value": requested_value,
            "effective_value": effective_value,
            "normalization_code": normalization_code,
        }
    )
