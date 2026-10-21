"""Face-mesh rules written into Agent-prepared people-bearing prompts.

User decision (2026-10-21, user accepts the provider-policy risk): Seedance
rejects reference images of the Agent's semi-realistic fictional characters as
possible real people. Agent Character Three-views therefore draw a face mesh,
Agent Storyboard grids keep it on everyone, and Agent Videos remove it.

The rules live only in the visible node prompt text. Nothing adds them at
provider submission, so a user who edits or deletes the rule gets exactly
what the prompt says (user rule, 2026-10-21). User-created nodes never get them.
"""

from __future__ import annotations


THREE_VIEW_FACE_MESH_RULE = (
    "Mandatory rule: cover every person's face in the image with a thin white line mesh."
)
STORYBOARD_FACE_MESH_RULE = (
    "Mandatory rule: every person in every panel of the storyboard grid has a thin white line "
    "face mesh. People from the bound references already have a face mesh; keep it and do not "
    "add a second layer."
)
VIDEO_FACE_MESH_REMOVAL_RULE = "Mandatory rule: remove every face mesh from all people."

FACE_MESH_RULES_BY_ROLE_VARIANT: dict[str, str] = {
    "character_turnaround": THREE_VIEW_FACE_MESH_RULE,
    "storyboard_grid": STORYBOARD_FACE_MESH_RULE,
    "video_segment": VIDEO_FACE_MESH_REMOVAL_RULE,
}
