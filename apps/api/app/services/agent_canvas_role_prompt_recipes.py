"""Versioned recipe registry for Agent Canvas role prompt preparation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_role_prompt_preparation import RolePromptVariantV2


@dataclass(frozen=True, slots=True)
class RolePromptRecipeRegistration:
    role_variant: RolePromptVariantV2
    recipe_id: str
    recipe_version: str
    allowed_context_selectors: tuple[str, ...]
    reference_purposes: tuple[str, ...]
    parameter_names: tuple[str, ...]
    positive_boundary: str
    negative_boundary: str
    recipe_digest: str


_RECIPE_DEFINITIONS: tuple[
    tuple[RolePromptVariantV2, tuple[str, ...], tuple[str, ...], tuple[str, ...], str, str],
    ...,
] = (
    ("world_view", ("requirements", "style"), (), (), "Concise world rules.", "No script."),
    (
        "product_main",
        ("requirements", "style", "world_view"),
        (),
        ("aspect_ratio", "size"),
        "One isolated product identity.",
        "No people or application scene.",
    ),
    (
        "product_multiview",
        ("requirements", "style", "bindings"),
        ("product_main_identity",),
        ("aspect_ratio", "size"),
        "Exact Product Main identity in multiple views.",
        "No application scene or main-prompt reuse.",
    ),
    (
        "prop",
        ("requirements", "style", "world_view"),
        (),
        ("aspect_ratio", "size"),
        "One isolated prop identity.",
        "No people or unrelated objects.",
    ),
    (
        "character_main",
        ("requirements", "style", "world_view"),
        (),
        ("aspect_ratio", "size"),
        "One illustrated full-body character identity.",
        "No photorealistic human, product, or scene.",
    ),
    (
        "character_turnaround",
        ("requirements", "style", "bindings"),
        ("character_main_identity",),
        ("aspect_ratio", "size"),
        "Exact Character Main identity in front, side, and back.",
        "No labels, product, or scene.",
    ),
    (
        "scene_board",
        ("requirements", "style", "world_view"),
        (),
        ("aspect_ratio", "size"),
        "One coherent environment board.",
        "No narrative subject activity or text.",
    ),
    (
        "script",
        ("requirements", "documents", "world_view"),
        (),
        ("duration_seconds",),
        "Editable narrative authority.",
        "No provider rendering syntax.",
    ),
    (
        "storyboard_grid",
        ("requirements", "documents", "style", "world_view", "bindings"),
        ("identity_reference",),
        ("aspect_ratio", "size", "duration_seconds"),
        "One text-free nine-beat Sequence grid.",
        "No labels or sibling prompt reuse.",
    ),
    (
        "video_segment",
        ("requirements", "documents", "style", "world_view", "bindings"),
        ("storyboard_grid",),
        ("duration_seconds", "aspect_ratio", "resolution", "audio_mode"),
        "One bounded video segment.",
        "No background music.",
    ),
    (
        "bgm",
        ("requirements", "documents", "style", "world_view"),
        (),
        ("duration_seconds",),
        "One pure instrumental track.",
        "No vocals, speech, ambience, or effects.",
    ),
    ("free_text", ("requirements",), (), (), "One focused text result.", "No hidden context."),
    (
        "free_image",
        ("requirements", "style", "bindings"),
        (),
        ("aspect_ratio", "size"),
        "One focused image.",
        "No hidden references.",
    ),
    (
        "free_video",
        ("requirements", "style", "bindings"),
        (),
        ("duration_seconds", "aspect_ratio", "resolution", "audio_mode"),
        "One focused video.",
        "No hidden references.",
    ),
    (
        "free_audio",
        ("requirements", "style", "bindings"),
        (),
        ("duration_seconds",),
        "One focused audio result.",
        "No hidden references.",
    ),
)


def _registration(
    definition: tuple[
        RolePromptVariantV2,
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        str,
        str,
    ],
) -> RolePromptRecipeRegistration:
    variant, selectors, purposes, parameters, positive, negative = definition
    recipe_id = f"adcraft.agent_canvas.{variant}"
    version = "1"
    payload = json.dumps(
        {
            "role_variant": variant,
            "recipe_id": recipe_id,
            "recipe_version": version,
            "allowed_context_selectors": selectors,
            "reference_purposes": purposes,
            "parameter_names": parameters,
            "positive_boundary": positive,
            "negative_boundary": negative,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return RolePromptRecipeRegistration(
        role_variant=variant,
        recipe_id=recipe_id,
        recipe_version=version,
        allowed_context_selectors=selectors,
        reference_purposes=purposes,
        parameter_names=parameters,
        positive_boundary=positive,
        negative_boundary=negative,
        recipe_digest=f"sha256:{sha256(payload.encode()).hexdigest()}",
    )


class RolePromptRecipeRegistry:
    """Resolve one immutable recipe for every supported role variant."""

    def __init__(
        self,
        registrations: tuple[RolePromptRecipeRegistration, ...] | None = None,
    ) -> None:
        values = registrations or tuple(_registration(item) for item in _RECIPE_DEFINITIONS)
        by_variant = {item.role_variant: item for item in values}
        if len(by_variant) != len(values):
            raise V2PersistenceError(
                "node_prompt_recipe_registry_invalid",
                "Role prompt recipe variants must be unique.",
                stage="role_prompt_recipe_registry",
            )
        self._by_variant = MappingProxyType(by_variant)

    def registrations(self) -> tuple[RolePromptRecipeRegistration, ...]:
        return tuple(self._by_variant.values())

    def resolve(self, role_variant: RolePromptVariantV2) -> RolePromptRecipeRegistration:
        try:
            return self._by_variant[role_variant]
        except KeyError as error:
            raise V2PersistenceError(
                "node_prompt_role_unsupported",
                "Role prompt variant is not registered.",
                stage="role_prompt_recipe_registry",
            ) from error
