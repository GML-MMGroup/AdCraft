"""Shared normalization of the intentional derived Video parameter lag."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal

from app.schemas.agent_canvas import CanvasNodeV2


def projection_consistency(
    node: CanvasNodeV2,
) -> Literal["absent", "in_sync", "review_advanced", "derived_lag", "conflict"]:
    """Classify editable prompt authority against the current Node revision."""

    projection = node.prompt_presentation
    if projection is None:
        return "absent"
    prompt = node.generation_prompt or ""
    if (
        projection.text != prompt
        or projection.prompt_digest != f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    ):
        return "conflict"
    if projection.revision == node.revision:
        return "in_sync"
    review_revision = node.metadata.get("guided_review_node_revision")
    if (
        projection.revision + 1 == node.revision
        and isinstance(review_revision, int)
        and not isinstance(review_revision, bool)
    ):
        if review_revision == node.revision:
            return "review_advanced"
        if review_revision == projection.revision:
            return "derived_lag"
    return "conflict"


def normalize_derived_parameter_prompt_authority(node: CanvasNodeV2) -> CanvasNodeV2:
    """Prepare valid authority to lag exactly once after a derived parameter write."""

    if projection_consistency(node) not in {"in_sync", "review_advanced", "derived_lag"}:
        return node
    projection = node.prompt_presentation
    assert projection is not None
    projection = projection.model_copy(update={"revision": node.revision})
    return node.model_copy(
        update={
            "prompt_presentation": projection,
            "metadata": {
                **node.metadata,
                "guided_review_node_revision": node.revision,
                "editable_prompt_projection": projection.model_dump(mode="json"),
            },
        }
    )


def resync_derived_parameter_lag(node: CanvasNodeV2) -> CanvasNodeV2:
    """Treat the derived Video parameter lag as in sync before another revision bump.

    A derived parameter write leaves the projection and review marker one
    revision behind on purpose. A later reference-only refresh would otherwise
    widen that lag to two, which no run can restore (production incident
    2026-10-27). The prompt text itself is unchanged, so the projection moves
    back in sync with the Node revision.
    """

    if projection_consistency(node) != "derived_lag":
        return node
    projection = node.prompt_presentation
    assert projection is not None
    return node.model_copy(
        update={
            "prompt_presentation": projection.model_copy(update={"revision": node.revision}),
            "metadata": {**node.metadata, "guided_review_node_revision": node.revision},
        }
    )
