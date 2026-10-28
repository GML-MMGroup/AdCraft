"""Shared normalization of the intentional derived Video parameter lag."""

from __future__ import annotations

from hashlib import sha256

from app.schemas.agent_canvas import CanvasNodeV2


def resync_derived_parameter_lag(node: CanvasNodeV2) -> CanvasNodeV2:
    """Treat the derived Video parameter lag as in sync before another revision bump.

    A derived parameter write leaves the projection and review marker one
    revision behind on purpose. A later reference-only refresh would otherwise
    widen that lag to two, which no run can restore (production incident
    2026-10-27). The prompt text itself is unchanged, so the projection moves
    back in sync with the Node revision.
    """

    projection = node.prompt_presentation
    prompt = str(node.generation_prompt or "")
    if (
        projection is None
        or projection.revision + 1 != node.revision
        or node.metadata.get("guided_review_node_revision") != projection.revision
        or projection.text != prompt
        or projection.prompt_digest != f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    ):
        return node
    return node.model_copy(
        update={
            "prompt_presentation": projection.model_copy(update={"revision": node.revision}),
            "metadata": {**node.metadata, "guided_review_node_revision": node.revision},
        }
    )
