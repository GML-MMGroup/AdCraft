"""Bounded authority projection and parameter resolution for role prompts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import cast

from pydantic import JsonValue

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.agent_canvas_role_prompt_preparation import (
    ResolvedNodeParameterV2,
    RoleBoundTextControlV2,
    RoleBindingSnapshotV2,
    RoleParameterSourceKindV2,
    RolePromptPreparationContextV2,
    RolePromptVariantV2,
)
from app.services.agent_canvas_role_prompt_recipes import RolePromptRecipeRegistration


_GLOBAL_REQUIREMENT_FIELDS = frozenset(
    {
        "aspect_ratio",
        "audio_mode",
        "creative_direction",
        "duration_seconds",
        "output_resolution",
        "response_locale",
        "spoken_language",
        "visual_style",
    }
)
_ROLE_REQUIREMENT_PREFIXES: dict[RolePromptVariantV2, tuple[str, ...]] = {
    "world_view": ("world_",),
    "product_main": ("product_",),
    "product_multiview": ("product_",),
    "prop": ("prop_",),
    "character_main": ("character_",),
    "character_turnaround": ("character_",),
    "scene_board": ("scene_",),
    "script": ("script_", "narrative_"),
    "storyboard_grid": ("storyboard_", "sequence_"),
    "video_segment": ("video_", "sequence_"),
    "bgm": ("bgm_", "music_"),
    "free_text": ("text_",),
    "free_image": ("image_",),
    "free_video": ("video_",),
    "free_audio": ("audio_",),
}
_STYLE_CONTROL_FIELDS = (
    "aspect_ratio",
    "audio_mode",
    "duration_seconds",
    "frame_rate",
    "model_ref",
    "output_resolution",
    "resolution",
    "size",
)
_ASPECT_RATIO = re.compile(r"^(?P<width>[1-9][0-9]*):(?P<height>[1-9][0-9]*)$")
_SIZE = re.compile(r"^(?P<width>[1-9][0-9]*)x(?P<height>[1-9][0-9]*)$")
ROLE_PARAMETER_CONTROL_NAMES = frozenset(
    {
        "aspect_ratio",
        "audio_mode",
        "duration_seconds",
        "generate_audio",
        "frame_rate",
        "model_ref",
        "output_resolution",
        "resolution",
        "size",
    }
)


def resolve_role_prompt_variant(node: CanvasNodeV2) -> RolePromptVariantV2:
    """Resolve one canonical role recipe from the current Node contract."""

    role = node.creative_role
    if role == "world_setting":
        return "world_view"
    if role == "product":
        asset_kind = str(node.structured_content.get("asset_kind") or "main")
        return "product_multiview" if asset_kind == "multi_view" else "product_main"
    if role == "prop":
        return "prop"
    if role == "character":
        asset_kind = str(node.structured_content.get("character_asset_kind") or "identity_master")
        return "character_turnaround" if asset_kind == "turnaround" else "character_main"
    mapping: dict[str, RolePromptVariantV2] = {
        "scene": "scene_board",
        "script": "script",
        "storyboard_sequence": "storyboard_grid",
        "storyboard_video": "video_segment",
        "bgm": "bgm",
        "general_text": "free_text",
        "general_image": "free_image",
        "general_video": "free_video",
        "general_audio": "free_audio",
    }
    try:
        return mapping[role]
    except KeyError as error:
        raise _error(
            "node_prompt_role_unsupported",
            "The Node role does not support prompt preparation.",
        ) from error


class RolePromptContextProjector:
    """Project only current, role-compatible authority into prompt preparation."""

    def project(
        self,
        node: CanvasNodeV2,
        stage_context: StageAuthoringContextV1,
        *,
        requirement_revision_id: str,
        requirement_revision_no: int,
        document_revisions: dict[str, int],
        bindings: tuple[RoleBindingSnapshotV2, ...],
        model_policy_revision: int,
        explicit_controls: dict[str, JsonValue] | None = None,
        bound_text_controls: tuple[RoleBoundTextControlV2, ...] = (),
        storyboard_parameters: dict[str, JsonValue] | None = None,
        style_parameters: dict[str, JsonValue] | None = None,
        installation_parameters: dict[str, JsonValue] | None = None,
        world_view_projection: str | None = None,
    ) -> RolePromptPreparationContextV2:
        if stage_context.workflow_id != node.workflow_id:
            raise _error(
                "node_prompt_context_stale",
                "Prompt context does not belong to the target Workflow.",
            )
        if any(
            binding.source_node_id and binding.source_node_revision is None for binding in bindings
        ):
            raise _error(
                "node_prompt_context_stale",
                "A bound Node reference is missing its exact revision.",
            )
        role_variant = resolve_role_prompt_variant(node)
        selected = stage_context.selected_concept
        selected_direction = node.summary_prompt or (
            selected.public_summary if selected is not None else None
        )
        response_locale = stage_context.requirement_facts.get("response_locale")
        return RolePromptPreparationContextV2(
            workflow_id=node.workflow_id,
            node_id=node.node_id,
            node_revision=node.revision,
            role_variant=role_variant,
            requirement_revision_id=requirement_revision_id,
            requirement_revision_no=requirement_revision_no,
            requirement_facts=_role_requirement_facts(
                stage_context.requirement_facts,
                role_variant,
            ),
            document_revisions=document_revisions,
            selected_direction=selected_direction,
            user_prompt=node.generation_prompt,
            response_locale=(response_locale if isinstance(response_locale, str) else "und"),
            internal_skill_ref=stage_context.internal_skill_ref,
            style_projection=_aesthetic_style_projection(stage_context.style_projection),
            world_view_projection=world_view_projection,
            bindings=bindings,
            explicit_controls=explicit_controls or {},
            bound_text_controls=bound_text_controls,
            node_parameters=node.parameters,
            storyboard_parameters=storyboard_parameters or {},
            style_parameters=style_parameters or {},
            installation_parameters=installation_parameters or {},
            model_policy_revision=model_policy_revision,
            created_at=datetime.now(timezone.utc),
        )


class RolePromptParameterResolver:
    """Resolve provider-neutral parameters with fixed, auditable precedence."""

    def resolve(
        self,
        context: RolePromptPreparationContextV2,
        recipe: RolePromptRecipeRegistration,
        *,
        model_capability: dict[str, JsonValue] | None = None,
    ) -> tuple[ResolvedNodeParameterV2, ...]:
        resolved: dict[str, ResolvedNodeParameterV2] = {}
        sources = (
            (
                "explicit_user",
                context.explicit_controls,
                context.requirement_revision_id,
                context.requirement_revision_no,
            ),
            ("node_parameter", context.node_parameters, context.node_id, context.node_revision),
            (
                "storyboard_plan",
                context.storyboard_parameters,
                "storyboard_plan",
                _document_revision(context, "storyboard_plan"),
            ),
            ("style_advice", context.style_parameters, "style_projection", None),
            (
                "installation_default",
                context.installation_parameters,
                "installation_policy",
                context.model_policy_revision,
            ),
        )
        for name in recipe.parameter_names:
            explicit = context.explicit_controls.get(name)
            if explicit is not None:
                resolved[name] = ResolvedNodeParameterV2(
                    name=name,
                    value=_validate_parameter(name, explicit, context.role_variant),
                    source_kind="explicit_user",
                    source_id=context.requirement_revision_id,
                    source_revision=context.requirement_revision_no,
                )
                continue
            bound = next(
                (item for item in context.bound_text_controls if item.name == name),
                None,
            )
            if bound is not None:
                resolved[name] = ResolvedNodeParameterV2(
                    name=name,
                    value=_validate_parameter(name, bound.value, context.role_variant),
                    source_kind="bound_text",
                    source_id=bound.source_node_id,
                    source_revision=bound.source_node_revision,
                )
                continue
            for source_kind, values, source_id, source_revision in sources:
                if name not in values:
                    continue
                value = _validate_parameter(name, values[name], context.role_variant)
                resolved[name] = ResolvedNodeParameterV2(
                    name=name,
                    value=value,
                    source_kind=cast(RoleParameterSourceKindV2, source_kind),
                    source_id=source_id,
                    source_revision=source_revision,
                )
                break
        if "size" in recipe.parameter_names and "aspect_ratio" in resolved:
            resolved["size"] = _resolve_image_size(
                resolved["aspect_ratio"],
                model_capability or {},
            )
        return tuple(resolved[name] for name in recipe.parameter_names if name in resolved)


def _role_requirement_facts(
    facts: dict[str, JsonValue],
    role_variant: RolePromptVariantV2,
) -> dict[str, JsonValue]:
    prefixes = _ROLE_REQUIREMENT_PREFIXES[role_variant]
    return {
        key: value
        for key, value in sorted(facts.items())
        if key in _GLOBAL_REQUIREMENT_FIELDS or key.startswith(prefixes)
    }


def _aesthetic_style_projection(value: str | None) -> str | None:
    if value is None:
        return None
    retained = []
    for line in value.splitlines():
        lowered = line.casefold()
        if any(re.search(rf"\b{re.escape(field)}\b", lowered) for field in _STYLE_CONTROL_FIELDS):
            continue
        if line.strip():
            retained.append(line.strip())
    return "\n".join(retained) or None


def _validate_parameter(
    name: str,
    value: JsonValue,
    role_variant: RolePromptVariantV2,
) -> JsonValue:
    if name == "duration_seconds":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise _parameter_error()
        if role_variant in {"video_segment", "free_video"} and value > 15:
            raise _parameter_error()
        return value
    if name == "aspect_ratio":
        if not isinstance(value, str) or _ASPECT_RATIO.fullmatch(value) is None:
            raise _parameter_error()
        return value
    if name == "resolution":
        if not isinstance(value, str) or not value.strip():
            raise _parameter_error()
        return value.strip()
    if name == "size":
        if not isinstance(value, str) or _SIZE.fullmatch(value) is None:
            raise _parameter_error()
        return value
    if name == "audio_mode":
        if value not in {"none", "bgm_only", "full"}:
            raise _parameter_error()
        return value
    if name == "generate_audio":
        if not isinstance(value, bool):
            raise _parameter_error()
        return value
    return value


def _resolve_image_size(
    aspect: ResolvedNodeParameterV2,
    capability: dict[str, JsonValue],
) -> ResolvedNodeParameterV2:
    match = _ASPECT_RATIO.fullmatch(str(aspect.value))
    if match is None:
        raise _parameter_error()
    ratio_width = int(match.group("width"))
    ratio_height = int(match.group("height"))
    max_width = _positive_int(capability.get("max_width"), default=1024)
    max_height = _positive_int(capability.get("max_height"), default=1024)
    width = max_width
    height = round(width * ratio_height / ratio_width)
    if height > max_height:
        height = max_height
        width = round(height * ratio_width / ratio_height)
    return ResolvedNodeParameterV2(
        name="size",
        value=f"{width}x{height}",
        source_kind=aspect.source_kind,
        source_id=aspect.source_id,
        source_revision=aspect.source_revision,
    )


def _positive_int(value: JsonValue | None, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


def _document_revision(context: RolePromptPreparationContextV2, key: str) -> int | None:
    return context.document_revisions.get(key)


def _parameter_error() -> V2PersistenceError:
    return _error(
        "node_prompt_parameter_conflict",
        "A role prompt parameter conflicts with its canonical contract.",
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="role_prompt_context_projector")
