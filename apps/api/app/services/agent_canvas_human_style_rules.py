"""Human rendering rules written into Agent-prepared node prompts.

User decision (2026-10-23, replacing the 2026-10-21 face-mesh rules): Seedance
rejects reference images of the Agent's semi-realistic fictional characters as
possible real people. Agent images that draw people therefore render them as
hand-painted color illustrations, and Agent Videos turn those painted people
into realistic live-action people.

The rules live only in the visible node prompt text. Nothing adds them at
provider submission, so a user who edits or deletes a rule gets exactly what
the prompt says (user rule, 2026-10-21). User-created nodes never get them.
"""

from __future__ import annotations


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

HUMAN_STYLE_RULES_BY_ROLE_VARIANT: dict[str, str] = {
    "character_main": PAINTED_PEOPLE_RULE,
    "character_turnaround": PAINTED_PEOPLE_RULE,
    "storyboard_grid": STORYBOARD_PAINTED_PEOPLE_RULE,
    "video_segment": VIDEO_REALISTIC_PEOPLE_RULE,
}
