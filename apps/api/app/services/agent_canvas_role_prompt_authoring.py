"""Strict deterministic fixture author for offline Agent Canvas prompt tests."""

from __future__ import annotations

from app.schemas.agent_canvas_role_prompt_preparation import (
    RoleCreativeBriefV2,
    RolePromptPreparationContextV2,
)


def deterministic_role_brief(
    context: RolePromptPreparationContextV2,
) -> RoleCreativeBriefV2:
    """Build schema-valid fixture content without adding production authority."""

    summary = context.user_prompt or context.selected_direction or "Current creative direction."
    variant = context.role_variant
    if variant == "world_view":
        value = {
            "role_variant": variant,
            "premise": summary,
            "era_and_place": "Current accepted era and place.",
            "world_rules": ["Preserve the accepted world rules."],
            "visual_continuity": ["Preserve the accepted visual continuity."],
        }
    elif variant in {"product_main", "product_multiview"}:
        value = {
            "role_variant": variant,
            "identity": summary,
            "geometry": "Preserve the accepted product geometry and proportions.",
            "materials": "Preserve the accepted product materials and finish.",
            "marks": "Preserve the accepted product marks.",
            "palette": "Preserve the accepted product palette.",
            **(
                {"views": ["front", "side", "back", "three-quarter", "detail"]}
                if variant == "product_multiview"
                else {}
            ),
        }
    elif variant == "prop":
        value = {
            "role_variant": variant,
            "identity": summary,
            "form": "Preserve the accepted prop form.",
            "materials": "Preserve the accepted prop materials.",
            "palette": "Preserve the accepted prop palette.",
        }
    elif variant in {"character_main", "character_turnaround"}:
        value = {
            "role_variant": variant,
            "identity": summary,
            "face_and_hair": "Preserve the accepted face and hairstyle.",
            "silhouette_and_proportions": "Preserve silhouette and proportions.",
            "wardrobe": "Preserve the accepted wardrobe and palette.",
            "accessories": "Preserve accepted accessories.",
            **({"views": ["front", "side", "back"]} if variant == "character_turnaround" else {}),
        }
    elif variant == "scene_board":
        value = {
            "role_variant": variant,
            "environment_identity": summary,
            "spatial_logic": "Preserve one coherent spatial layout.",
            "lighting": "Preserve the accepted lighting.",
            "materials": "Preserve the accepted materials.",
            "atmosphere": "Preserve the accepted atmosphere.",
            "views": [f"Environment view {index}" for index in range(1, 10)],
        }
    elif variant == "script":
        value = {
            "role_variant": variant,
            "narrative": summary,
            "timing": "Follow the accepted timing.",
            "dialogue": "",
            "voiceover": "",
        }
    elif variant == "storyboard_grid":
        value = {
            "role_variant": variant,
            "sequence_summary": summary,
            "beats": [f"Ordered beat {index}" for index in range(1, 10)],
            "visual_language": "Preserve the accepted visual language.",
        }
    elif variant == "video_segment":
        duration = float(context.explicit_controls.get("duration_seconds") or 5)
        value = {
            "role_variant": variant,
            "segment_summary": summary,
            "duration_seconds": min(duration, 15),
            "action": "Follow the accepted ordered action.",
            "dialogue": "",
            "voiceover": "",
            "ambience": "Preserve scene ambience.",
            "action_effects": "Use synchronized action effects.",
            "target_style": context.style_projection or "Accepted campaign style.",
        }
    elif variant == "bgm":
        value = {
            "role_variant": variant,
            "music_summary": summary,
            "duration_seconds": float(context.explicit_controls.get("duration_seconds") or 30),
            "pace": "Follow the accepted pace.",
            "energy_curve": "Follow the accepted narrative arc.",
            "instrumentation": "Instrumental commercial arrangement.",
            "mood": "Accepted campaign mood.",
        }
    else:
        value = {"role_variant": variant, "prompt": summary}
    return RoleCreativeBriefV2.model_validate(value)
