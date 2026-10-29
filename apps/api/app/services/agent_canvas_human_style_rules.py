"""Human rendering rules written into Agent-prepared node prompts.

Image face handling preserves the selected rendering style and applies only to
realistic human faces and exposed human skin. Non-human characters retain their
selected style. Video conversion rules require an explicit live-action mode.
Historical constants remain available for reading saved prompt evidence.

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

FACE_ONLY_CHARACTER_RULE = (
    "Mandatory rule: Preserve the selected visual style. If a realistic human face appears, "
    "render only the human face, ears, neck and hands as an obvious colored-pencil drawing "
    "with visible cross-hatching, outlines and paper grain, retaining natural skin tones and "
    "accurate facial proportions. Preserve the selected treatment of hair, clothing, bodies, "
    "materials and background. Do not apply this face treatment to animals, robots, creatures, "
    "objects or other non-human characters, and do not turn an intentionally stylized face "
    "into a realistic human face."
)
FACE_ONLY_STORYBOARD_RULE = (
    "Mandatory rule: Preserve the selected visual style in every panel. If realistic human "
    "faces appear, including background extras and crowds, render only their faces, ears, "
    "necks and hands as obvious colored-pencil drawings with visible cross-hatching, outlines "
    "and paper grain, retaining natural skin tones and accurate facial proportions. Preserve "
    "the selected treatment of environments, lighting, materials, clothing, hair and bodies. "
    "Keep animals, robots, creatures, objects and other non-human characters in their selected "
    "style; do not restyle them or turn intentionally stylized faces into realistic human faces."
)


def human_style_rule(
    context: CharacterMainRoleBriefV2 | RolePromptPreparationContextV2,
) -> str | None:
    """Select from the Character brief or the downstream role's explicit Bindings."""
    if isinstance(context, CharacterMainRoleBriefV2):
        return FACE_ONLY_CHARACTER_RULE if context.human_face is not False else None
    characters = tuple(item for item in context.bindings if item.source_role == "character")
    if any(item.character_human_face is not False for item in characters):
        if context.role_variant == "storyboard_grid":
            return FACE_ONLY_STORYBOARD_RULE
        if context.role_variant in {"video_segment", "free_video"} and (
            context.video_representation_mode == "illustration_to_live_action"
        ):
            return REAL_PEOPLE_VIDEO_RULE
    return None
