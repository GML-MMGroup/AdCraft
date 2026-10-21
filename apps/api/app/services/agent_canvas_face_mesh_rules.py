"""Face-mesh provider rules for Agent-authored people-bearing nodes.

User decision (2026-10-21, user accepts the provider-policy risk): Seedance
rejects reference images of the Agent's semi-realistic fictional characters as
possible real people. Agent Character Three-views therefore draw a face mesh,
Agent Storyboard grids keep it on everyone, and Agent Videos remove it. The
rules are added at provider-prompt time so ready prompts are never re-authored,
and never to user-created nodes or their inputs.
"""

from __future__ import annotations

from app.schemas.agent_canvas import CanvasNodeV2
from app.services.agent_canvas_node_ownership import is_user_authored


THREE_VIEW_FACE_MESH_RULE = (
    "Mandatory rule: cover every person's face in the image with a thin white line mesh."
)
STORYBOARD_FACE_MESH_RULE = (
    "Mandatory rule: every person in every panel of the storyboard grid has a thin white line "
    "face mesh. People from the bound references already have a face mesh; keep it and do not "
    "add a second layer."
)
VIDEO_FACE_MESH_REMOVAL_RULE = "Mandatory rule: remove every face mesh from all people."


def face_mesh_rule(node: CanvasNodeV2) -> str | None:
    """Return the provider rule for an Agent people-bearing node, if any."""

    if is_user_authored(node):
        return None
    if node.creative_role == "character" and (
        node.structured_content.get("character_asset_kind") == "turnaround"
        or node.prompt_preparation.role_variant == "character_turnaround"
    ):
        return THREE_VIEW_FACE_MESH_RULE
    if node.creative_role == "storyboard_sequence":
        return STORYBOARD_FACE_MESH_RULE
    if node.creative_role == "storyboard_video":
        return VIDEO_FACE_MESH_REMOVAL_RULE
    return None


def with_face_mesh_rule(prompt: str, node: CanvasNodeV2) -> str:
    """Append the node's face-mesh rule once; other prompts are returned unchanged."""

    rule = face_mesh_rule(node)
    if rule is None or rule in prompt:
        return prompt
    return f"{prompt}\n\n{rule}"
