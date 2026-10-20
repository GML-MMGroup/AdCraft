"""Proof and validation helpers for derived visual prompt reuse."""

from hashlib import sha256
import json

from pydantic import ValidationError

from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_derivative_prompt_reuse import DerivativePromptReuseProofV1
from app.schemas.agent_canvas_role_prompt_preparation import RolePromptPreparationContextV2


def derivative_prompt_authority_digest(
    node: CanvasNodeV2,
    context: RolePromptPreparationContextV2,
    *,
    stage_digest: str,
    recipe_digest: str,
) -> str | None:
    """Ignore only source publication lineage, retaining creative authority."""

    if not _is_supported_derivative(node, context):
        return None
    payload = context.model_dump(mode="json", exclude={"node_revision", "created_at"})
    if context.role_variant == "scene_board":
        # Scene Multi-view's own projection is compiler output.  It is absent
        # on the first preparation and present after that preparation, so it
        # cannot be part of the authority identity used for reuse.
        payload["scene_environment_projection"] = None
        payload["scene_projection_required"] = False
    lineage = {"source_node_revision", "asset_id", "asset_version_id"}
    bindings = [item.model_dump(mode="json", exclude=lineage) for item in context.bindings]
    payload["bindings"] = bindings
    payload["binding_digest"] = _digest(bindings)
    for block in payload["context_blocks"]:
        if block["block_id"] == "bindings" and block["source_kind"] == "bindings":
            block["source_digest"] = _digest(bindings)
            block["effective_constraints_digest"] = _digest(bindings)
    return _digest(
        {
            "context": payload,
            "stage_digest": stage_digest,
            "recipe_digest": recipe_digest,
            "model_selection_mode": node.model_selection_mode,
            "model_ref": node.model_ref,
        }
    )


def derivative_prompt_reuse_proof(
    *,
    authority_digest: str,
    prompt: str,
    content: dict[str, object],
    brief_digest: str,
) -> DerivativePromptReuseProofV1:
    return DerivativePromptReuseProofV1(
        authority_digest=authority_digest,
        prompt_digest=f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}",
        content_digest=_digest(content),
        brief_digest=brief_digest,
    )


def can_reuse_derivative_prompt(
    node: CanvasNodeV2,
    context: RolePromptPreparationContextV2,
    *,
    authority_digest: str,
) -> bool:
    """Accept only an untouched prepared prompt owned by the compiler/Agent."""

    if not _is_supported_derivative(node, context):
        return False
    presentation = node.prompt_presentation
    prompt = node.generation_prompt
    if (
        not prompt
        or presentation is None
        or presentation.source not in {"agent_authored", "deterministic_projection"}
        or presentation.text != prompt
        or presentation.brief_digest is None
        or presentation.prompt_digest != f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
    ):
        return False
    raw_proof = node.metadata.get("prepared_derivative_prompt")
    if raw_proof is None:
        # Nodes created before this proof was introduced remain safe to replay
        # when their visible prompt projection is intact.  The repository only
        # reaches this path for a dependency successor, never a user edit.
        return True
    try:
        proof = DerivativePromptReuseProofV1.model_validate(raw_proof)
    except ValidationError:
        return False
    expected = derivative_prompt_reuse_proof(
        authority_digest=authority_digest,
        prompt=prompt,
        content=node.structured_content,
        brief_digest=presentation.brief_digest,
    )
    return proof == expected


def _is_supported_derivative(
    node: CanvasNodeV2,
    context: RolePromptPreparationContextV2,
) -> bool:
    if context.role_variant == "product_multiview":
        return (
            node.creative_role == "product"
            and node.structured_content.get("asset_kind") == "multi_view"
        )
    return (
        context.role_variant == "scene_board"
        and node.creative_role == "scene"
        and (
            node.structured_content.get("scene_asset_kind") == "multi_view"
            or node.parameters.get("scene_asset_kind") == "multi_view"
        )
    )


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"
