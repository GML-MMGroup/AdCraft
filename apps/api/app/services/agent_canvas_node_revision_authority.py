"""One transition policy for mutable Node and editable-prompt revisions.

Call inside the writer's existing transaction, after checking its stored preimage.
This module never changes frozen runs, submits work, or repairs unexplained drift.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Literal

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.services.agent_canvas_prompt_projection_lag import projection_consistency

PromptRevisionIntent = Literal["carry", "author", "invalidate", "review"]


def reconcile_node_prompt_revision(
    current: CanvasNodeV2,
    candidate: CanvasNodeV2,
    *,
    intent: PromptRevisionIntent = "carry",
) -> CanvasNodeV2:
    """Bind an authorized successor's prompt to its revision without rewriting text.

    Carry/review inherit proven authority. Author accepts an explicit replacement,
    even if the old projection is corrupt. Invalidation can clear an old prompt,
    but cannot reauthorize corrupt retained text. Review markers follow unchanged
    authority only when they covered the preimage; authoring invalidates them
    unless the writer explicitly publishes a newly reviewed projection.
    """
    if intent == "carry" and candidate.revision == current.revision:
        # Existing operational updates do not advance authoring. They may
        # change execution/preparation status, never content or prompt authority.
        runtime_fields = {
            "status",
            "output_asset_id",
            "error",
            "updated_at",
            "prompt_preparation",
            "prompt_context_snapshot_id",
        }
        if current.model_dump(exclude=runtime_fields) != candidate.model_dump(
            exclude=runtime_fields
        ):
            raise _conflict()
        if (
            candidate.prompt_preparation.status == "ready"
            and current.prompt_preparation.status != "ready"
        ):
            raise _conflict()
        return candidate
    if (
        current.node_id != candidate.node_id
        or current.workflow_id != candidate.workflow_id
        or candidate.revision != current.revision + 1
    ):
        raise _conflict()
    if intent not in {"carry", "author", "invalidate", "review"}:
        raise ValueError("Unsupported Node prompt revision intent.")
    state = projection_consistency(current)
    metadata = dict(candidate.metadata)
    projection = candidate.prompt_presentation
    if intent == "author":
        if projection is not None and (
            projection.revision != candidate.revision or not _matches(candidate)
        ):
            raise _conflict()
        if projection is None and candidate.generation_prompt and current.prompt_presentation:
            raise _conflict()
    elif intent == "invalidate" and not candidate.generation_prompt:
        projection = None
    else:
        if state == "conflict" or candidate.generation_prompt != current.generation_prompt:
            raise _conflict()
        # A carry cannot inject a new locale, origin, text, or digest under cover
        # of a revision update. Callers authoring replacements must say so.
        if projection is not None and current.prompt_presentation is not None:
            if (
                projection.model_copy(update={"revision": current.prompt_presentation.revision})
                != current.prompt_presentation
            ):
                raise _conflict()
        elif projection != current.prompt_presentation:
            raise _conflict()
        projection = current.prompt_presentation

    if projection is not None:
        projection = projection.model_copy(update={"revision": candidate.revision})
        metadata["editable_prompt_projection"] = projection.model_dump(mode="json")
    else:
        metadata.pop("editable_prompt_projection", None)
    marker = current.metadata.get("guided_review_node_revision")
    reviewed = type(marker) is int and (marker == current.revision or state == "derived_lag")
    if intent == "review":
        metadata["guided_review_node_revision"] = candidate.revision
    elif intent in {"author", "invalidate"}:
        if (
            intent == "invalidate"
            or metadata.get("guided_review_node_revision") != candidate.revision
        ):
            metadata.pop("guided_review_node_revision", None)
    elif reviewed:
        metadata["guided_review_node_revision"] = candidate.revision
    else:
        # A carry must not manufacture approval from candidate metadata.
        metadata.pop("guided_review_node_revision", None)
        if marker is not None:
            metadata["guided_review_node_revision"] = marker
    return candidate.model_copy(update={"prompt_presentation": projection, "metadata": metadata})


def _matches(node: CanvasNodeV2) -> bool:
    projection = node.prompt_presentation
    prompt = node.generation_prompt or ""
    return (
        projection is not None
        and projection.text == prompt
        and projection.prompt_digest == (f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}")
    )


def _conflict() -> V2PersistenceError:
    return V2PersistenceError(
        "prompt_revision_conflict",
        "The editable prompt projection does not match the Node revision.",
        stage="agent_canvas_node_revision_authority",
    )
