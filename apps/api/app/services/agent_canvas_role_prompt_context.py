"""Bounded authority projection and parameter resolution for role prompts."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
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
    RolePromptContextBlockV2,
    RoleParameterSourceKindV2,
    RolePromptPreparationContextV2,
    RolePromptVariantV2,
)
from app.services.agent_canvas_role_prompt_recipes import RolePromptRecipeRegistration
from app.services.agent_canvas_video_representation import resolve_video_representation_mode


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
        "video_representation_mode",
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
    "video_representation_mode",
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
        "video_representation_mode",
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
        context_blocks: tuple[RolePromptContextBlockV2, ...] = (),
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
        occurrence_id: str | None = None
        character_phase = None
        if role_variant in {"character_main", "character_turnaround"}:
            occurrence_value = node.metadata.get("occurrence_id")
            phase_value = node.metadata.get("character_phase")
            ledger_revision_id = node.metadata.get("requirement_revision_id")
            ledger_revision_no = node.metadata.get("requirement_revision_no")
            if (
                not isinstance(occurrence_value, str)
                or stage_context.occurrence_id != occurrence_value
            ):
                raise _error(
                    "character_occurrence_invalid",
                    "Character prompt context does not match the current occurrence.",
                )
            expected_phase = "main" if role_variant == "character_main" else "turnaround"
            if phase_value != expected_phase:
                raise _error(
                    "character_authoring_phase_invalid",
                    "Character prompt context does not match the current phase.",
                )
            if (
                ledger_revision_id != requirement_revision_id
                or ledger_revision_no != requirement_revision_no
            ):
                raise _error(
                    "node_prompt_context_stale",
                    "Character prompt context does not match the frozen Requirement Ledger.",
                )
            if (
                stage_context.internal_skill_ref
                != "agent/skills/video_agent_character_design/SKILL.md"
            ):
                raise _error(
                    "node_prompt_context_stale",
                    "Character prompt context requires the internal Character Skill.",
                )
            occurrence_id = occurrence_value
            character_phase = expected_phase
        selected = stage_context.selected_concept
        selected_direction = node.summary_prompt or (
            selected.public_summary if selected is not None else None
        )
        response_locale = stage_context.requirement_facts.get("response_locale")
        resolved_context_blocks = context_blocks or _default_context_blocks(
            requirement_revision_id=requirement_revision_id,
            requirement_revision_no=requirement_revision_no,
            requirement_facts=_role_requirement_facts(
                stage_context.requirement_facts,
                role_variant,
            ),
            selected_direction=selected_direction,
            user_prompt=_authoring_user_prompt(node),
            style_projection=_aesthetic_style_projection(
                stage_context.style_projection,
                role_variant=role_variant,
            ),
            world_view_projection=world_view_projection,
            document_revisions=document_revisions,
            bindings=bindings,
        )
        world_view_block_id = next(
            (item.block_id for item in resolved_context_blocks if item.source_kind == "world_view"),
            None,
        )
        representation = resolve_video_representation_mode(
            explicit_control=(explicit_controls or {}).get("video_representation_mode"),
            skill_mode=(
                (style_parameters or {}).get("video_representation_mode")
                or stage_context.video_representation_mode
            ),
            skill_source_id=(
                stage_context.video_representation_source_id
                or (style_parameters or {}).get("video_representation_source_id")
                or "video-skill"
            ),
        )
        return RolePromptPreparationContextV2(
            workflow_id=node.workflow_id,
            node_id=node.node_id,
            node_revision=node.revision,
            role_variant=role_variant,
            requirement_revision_id=requirement_revision_id,
            requirement_revision_no=requirement_revision_no,
            occurrence_id=occurrence_id,
            character_phase=character_phase,
            requirement_facts=_role_requirement_facts(
                stage_context.requirement_facts,
                role_variant,
            ),
            document_revisions=document_revisions,
            selected_direction=selected_direction,
            user_prompt=_authoring_user_prompt(node),
            response_locale=(response_locale if isinstance(response_locale, str) else "und"),
            internal_skill_ref=stage_context.internal_skill_ref,
            style_projection=_aesthetic_style_projection(
                stage_context.style_projection,
                role_variant=role_variant,
            ),
            world_view_projection=world_view_projection,
            bindings=bindings,
            explicit_controls=explicit_controls or {},
            bound_text_controls=bound_text_controls,
            node_parameters=node.parameters,
            storyboard_parameters=storyboard_parameters or {},
            style_parameters=style_parameters or {},
            installation_parameters=installation_parameters or {},
            context_blocks=resolved_context_blocks,
            world_view_block_id=world_view_block_id,
            video_representation_mode=(
                representation.mode if role_variant in {"video_segment", "free_video"} else None
            ),
            video_representation_source=(
                representation.source if role_variant in {"video_segment", "free_video"} else None
            ),
            video_representation_source_id=representation.source_id,
            video_representation_digest=(
                representation.digest if role_variant in {"video_segment", "free_video"} else None
            ),
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
            if name == "video_representation_mode" and context.video_representation_mode:
                source_kind = (
                    "explicit_user"
                    if context.video_representation_source == "explicit_user"
                    else "style_advice"
                )
                resolved[name] = ResolvedNodeParameterV2(
                    name=name,
                    value=context.video_representation_mode,
                    source_kind=cast(RoleParameterSourceKindV2, source_kind),
                    source_id=(
                        context.requirement_revision_id
                        if source_kind == "explicit_user"
                        else (context.video_representation_source_id or "video-skill")
                    ),
                    source_revision=(
                        context.requirement_revision_no if source_kind == "explicit_user" else None
                    ),
                )
                continue
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
    projected = {
        key: value
        for key, value in sorted(facts.items())
        if (key in _GLOBAL_REQUIREMENT_FIELDS or key.startswith(prefixes))
        and key not in {"character_occurrences", "character_roster"}
    }
    return projected


def _aesthetic_style_projection(
    value: str | None,
    *,
    role_variant: RolePromptVariantV2,
) -> str | None:
    if value is None:
        return None
    retained = []
    for line in value.splitlines():
        lowered = line.casefold()
        if any(re.search(rf"\b{re.escape(field)}\b", lowered) for field in _STYLE_CONTROL_FIELDS):
            continue
        if role_variant in {"character_main", "character_turnaround"} and any(
            term in lowered
            for term in (
                "photorealistic",
                "photo-realistic",
                "live action",
                "live-action",
                "group portrait",
                "whole cast",
                "text label",
                "labels",
            )
        ):
            continue
        if line.strip():
            retained.append(line.strip())
    return "\n".join(retained) or None


def _authoring_user_prompt(node: CanvasNodeV2) -> str | None:
    prompt = node.generation_prompt
    if not prompt:
        return None
    prepared_digest = node.metadata.get("prompt_digest")
    if (
        node.metadata.get("prompt_recipe_id")
        and isinstance(prepared_digest, str)
        and prepared_digest == sha256(prompt.encode("utf-8")).hexdigest()
    ):
        return None
    return prompt


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


def _default_context_blocks(
    *,
    requirement_revision_id: str,
    requirement_revision_no: int,
    requirement_facts: dict[str, JsonValue],
    selected_direction: str | None,
    user_prompt: str | None,
    style_projection: str | None,
    world_view_projection: str | None,
    document_revisions: dict[str, int],
    bindings: tuple[RoleBindingSnapshotV2, ...],
) -> tuple[RolePromptContextBlockV2, ...]:
    blocks: list[RolePromptContextBlockV2] = []

    def add(
        *,
        block_id: str,
        source_kind: str,
        source_id: str,
        value: object,
        ownership: str,
        precedence: int,
        disposition: str = "preserve",
    ) -> None:
        digest = _prefixed_digest(value)
        blocks.append(
            RolePromptContextBlockV2(
                block_id=block_id,
                source_kind=source_kind,  # type: ignore[arg-type]
                source_id=source_id,
                source_digest=digest,
                ownership=ownership,  # type: ignore[arg-type]
                precedence=precedence,
                effective_constraints_digest=digest,
                disposition=disposition,  # type: ignore[arg-type]
            )
        )

    add(
        block_id=f"requirements:{requirement_revision_id}:{requirement_revision_no}",
        source_kind="requirements",
        source_id=f"{requirement_revision_id}:{requirement_revision_no}",
        value=requirement_facts,
        ownership="compiler",
        precedence=0,
    )
    if selected_direction:
        add(
            block_id="selected-direction",
            source_kind="selected_direction",
            source_id="selected_direction",
            value=selected_direction,
            ownership="compiler",
            precedence=1,
        )
    if user_prompt:
        add(
            block_id="user-prompt",
            source_kind="user_prompt",
            source_id="user_prompt",
            value=user_prompt,
            ownership="user",
            precedence=2,
        )
    if style_projection:
        add(
            block_id="style-projection",
            source_kind="style",
            source_id="style_projection",
            value=style_projection,
            ownership="unknown",
            precedence=3,
        )
    if world_view_projection:
        world_digest = _prefixed_digest(world_view_projection)
        add(
            block_id=f"world_view:{world_digest[7:39]}",
            source_kind="world_view",
            source_id=f"world_view:{world_digest[7:39]}",
            value=world_view_projection,
            ownership="unknown",
            precedence=4,
            disposition="retain_unknown",
        )
    if document_revisions:
        add(
            block_id="documents",
            source_kind="documents",
            source_id="documents",
            value=document_revisions,
            ownership="compiler",
            precedence=5,
        )
    if bindings:
        add(
            block_id="bindings",
            source_kind="bindings",
            source_id="bindings",
            value=[item.model_dump(mode="json") for item in bindings],
            ownership="compiler",
            precedence=6,
        )
    return tuple(sorted(blocks, key=lambda item: (item.precedence, item.block_id)))


def _prefixed_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=lambda item: item.model_dump(mode="json"),
    )
    return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"
