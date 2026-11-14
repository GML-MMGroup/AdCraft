"""Visual identity authority for existing images selected by the user."""

from app.schemas.agent_canvas import CanvasNodeV2


SELECTED_REFERENCE_APPEARANCE = (
    "Use the user-selected reference image as appearance authority. Its visible design "
    "takes precedence over earlier written appearance in requirements, scripts, proposals "
    "and summaries. Preserve story actions, product functions and shot intent. Do not "
    "invent unseen appearance or treat an old description as an observation of this image."
)


def selected_reference_facts(node: CanvasNodeV2) -> dict[str, object]:
    """Omit legacy copied appearance while preserving exact role and occurrence mapping."""
    if (
        node.execution_mode != "source_only"
        or node.node_type != "image"
        or node.creative_role not in {"product", "character", "scene"}
        or node.output_asset_id is None
    ):
        return {}
    facts: dict[str, object] = {
        "appearance_authority": "selected_reference_image",
        "appearance_instruction": SELECTED_REFERENCE_APPEARANCE,
    }
    if node.creative_role == "character":
        for name, value in (
            ("occurrence_id", node.metadata.get("occurrence_id")),
            ("character_asset_kind", node.structured_content.get("character_asset_kind")),
        ):
            if isinstance(value, str):
                facts[name] = value
    return facts
