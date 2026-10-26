"""Human rendering rules written into Agent-prepared node prompts.

User decision (2026-10-26, replacing the 2026-10-23 paint-every-person rules):
characters with realistic human faces use heavy colored-pencil faces and exposed
skin in photographic Character and Storyboard references so Seedance accepts
them. Agent Videos render real people in photorealistic live action. Non-human
and intentionally stylized characters get no special rule. Historical unknown
human-face values retain the legacy painted-person rules.

The rules live only in the visible node prompt text. Nothing adds them at
provider submission, so a user who edits or deletes a rule gets exactly what
the prompt says (user rule, 2026-10-21). User-created nodes never get them.
"""

from __future__ import annotations

from app.schemas.agent_canvas_role_prompt_preparation import (
    CharacterMainRoleBriefV2,
    RolePromptPreparationContextV2,
)

PAINTED_PEOPLE_RULE = (
    "Mandatory rule: render every person as a hand-painted color illustration with visible "
    "brushstrokes and gouache or watercolor texture, including painted skin and faces; "
    "never photorealistic."
)
STORYBOARD_PAINTED_PEOPLE_RULE = (
    "Mandatory rule: in every panel, render every person, including background extras and "
    "crowds, as a hand-painted color illustration with visible brushstrokes and gouache or "
    "watercolor texture, including painted skin and faces; never photorealistic."
)
VIDEO_REALISTIC_PEOPLE_RULE = (
    "Mandatory rule: render every person as a photorealistic real person in live action. The "
    "painted people in the bound references define identity only: keep each person's face "
    "shape, hairstyle, clothing, body proportions, pose and the composition, but do not keep "
    "the painted look on people. This rule overrides any instruction to keep people "
    "illustrated."
)

PENCIL_FACE_CHARACTER_RULE = (
    "Mandatory rule: this is a photographic character reference, but the face, ears, neck and "
    "hands are an obvious hand-drawn colored-pencil drawing over the photo: bold dense "
    "cross-hatching strokes, colored-pencil outlines around the eyes, nose, lips and jawline, "
    "flat paper-white highlights and visible paper grain, in natural skin tones without blush, "
    "so even at small size the skin clearly reads as a pencil drawing and never as photographed "
    "skin. The pencil strokes are drawing marks, not freckles, spots or blemishes. Keep accurate "
    "realistic facial proportions. Hair, clothing, body and background stay photographic."
)
PENCIL_FACE_STORYBOARD_RULE = (
    "Mandatory rule: environments, clothing, hair and bodies are cinematic photography, but in "
    "every panel the face, ears, neck and hands of every person, including background extras and "
    "crowds, are an obvious hand-drawn colored-pencil drawing: bold dense cross-hatching strokes, "
    "colored-pencil outlines around the eyes, nose, lips and jawline, flat paper-white highlights "
    "and visible paper grain, in natural skin tones without blush, so even small faces clearly "
    "read as pencil drawings and never as photographed skin. Keep accurate facial proportions."
)
REAL_PEOPLE_VIDEO_RULE = (
    "Mandatory rule: render the whole video as photorealistic live action and every person as a "
    "real person with real, clean photographic skin in natural skin tones and cinematic lighting. "
    "The colored-pencil drawing on faces and skin in the bound references defines identity only: "
    "keep each person's face shape, facial features, hairstyle, clothing and body proportions, "
    "but never show pencil strokes, hatching, outlines, paper texture, freckles or heavy blush "
    "on skin. This rule overrides any instruction to keep people or the video illustrated."
)


def human_style_rule(
    context: CharacterMainRoleBriefV2 | RolePromptPreparationContextV2,
) -> str | None:
    """Select from the Character brief or the downstream role's explicit Bindings."""
    if isinstance(context, CharacterMainRoleBriefV2):
        if context.human_face is True:
            return PENCIL_FACE_CHARACTER_RULE
        return PAINTED_PEOPLE_RULE if context.human_face is None else None
    characters = tuple(item for item in context.bindings if item.source_role == "character")
    if any(item.character_human_face is True for item in characters):
        if context.role_variant == "storyboard_grid":
            return PENCIL_FACE_STORYBOARD_RULE
        if context.role_variant in {"video_segment", "free_video"}:
            return REAL_PEOPLE_VIDEO_RULE
    elif any(item.character_human_face is None for item in characters):
        if context.role_variant == "storyboard_grid":
            return STORYBOARD_PAINTED_PEOPLE_RULE
        if context.role_variant == "video_segment":
            return VIDEO_REALISTIC_PEOPLE_RULE
    return None
