"""Proof of unchanged Turnaround creative authority across Main publication."""

from __future__ import annotations

from hashlib import sha256
import json
from pydantic import ValidationError, JsonValue

from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_character_prompt_reuse import (
    CharacterPromptReuseProofV1,
    LegacyCharacterPromptProofV1,
)
from app.schemas.agent_canvas_role_prompt_preparation import (
    CharacterIdentityAuthorityProjectionV1,
    RolePromptPreparationContextV2,
)


def character_prompt_authority_digest(
    node: CanvasNodeV2,
    context: RolePromptPreparationContextV2,
    *,
    stage_digest: str,
    recipe_digest: str,
) -> str:
    """Ignore only publication lineage; keep all creative and Binding authority."""

    payload = context.model_dump(mode="json", exclude={"node_revision", "created_at"})
    parent = context.character_identity_projection
    if context.role_variant == "character_turnaround" and parent is not None:
        lineage = {
            "source_node_revision",
            "source_asset_id",
            "source_asset_version_id",
            "projection_digest",
        }
        payload["character_identity_projection"] = parent.model_dump(mode="json", exclude=lineage)
        bindings = [
            item.model_dump(
                mode="json", exclude={"source_node_revision", "asset_id", "asset_version_id"}
            )
            if item.source_node_id == parent.source_node_id
            and item.character_phase == "main"
            and item.occurrence_id == parent.occurrence_id
            else item.model_dump(mode="json")
            for item in context.bindings
        ]
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


def character_prompt_reuse_proof(
    *,
    authority_digest: str,
    prompt: str,
    content: dict[str, JsonValue],
    brief_digest: str,
) -> CharacterPromptReuseProofV1:
    return CharacterPromptReuseProofV1(
        authority_digest=authority_digest,
        prompt_digest=f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}",
        content_digest=_digest(content),
        brief_digest=brief_digest,
    )


def can_reuse_character_prompt(node: CanvasNodeV2, authority_digest: str) -> bool:
    """Fail closed on missing proof, user ownership, edits or context changes."""

    presentation = node.prompt_presentation
    if (
        node.creative_role != "character"
        or node.metadata.get("character_phase") != "turnaround"
        or not node.generation_prompt
        or presentation is None
        or presentation.source not in {"agent_authored", "deterministic_projection"}
        or presentation.text != node.generation_prompt
        or presentation.brief_digest is None
    ):
        return False
    try:
        saved = CharacterPromptReuseProofV1.model_validate(
            node.metadata.get("prepared_character_prompt")
        )
    except ValidationError:
        return False
    expected = character_prompt_reuse_proof(
        authority_digest=authority_digest,
        prompt=node.generation_prompt,
        content=node.structured_content,
        brief_digest=presentation.brief_digest,
    )
    return saved == expected and presentation.prompt_digest == expected.prompt_digest


def retain_legacy_character_proof(
    node: CanvasNodeV2, stage_digest: str | None
) -> dict[str, JsonValue]:
    """Seed only complete Ready single-parent evidence before invalidation strips it."""

    presentation = node.prompt_presentation
    if (
        node.creative_role != "character"
        or node.metadata.get("character_phase") != "turnaround"
        or "prepared_character_prompt" in node.metadata
        or node.prompt_preparation.status != "ready"
        or not stage_digest
        or stage_digest != node.metadata.get("prompt_context_digest")
        or presentation is None
        or presentation.source not in {"agent_authored", "deterministic_projection"}
        or presentation.text != node.generation_prompt
    ):
        return {}
    snapshots = node.metadata.get("prepared_reference_snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != 1:
        return {}
    try:
        proof = LegacyCharacterPromptProofV1.model_validate(
            {
                "stage_digest": stage_digest,
                "recipe_digest": node.prompt_preparation.recipe_digest,
                "node_inputs_digest": _node_inputs_digest(node),
                "content_digest": _digest(node.structured_content),
                "prompt_digest": presentation.prompt_digest,
                "brief_digest": presentation.brief_digest,
                "parent": snapshots[0],
            }
        )
    except ValidationError:
        return {}
    return {"retained_legacy_character_prompt": proof.model_dump(mode="json")}


def can_reuse_legacy_character_prompt(
    node: CanvasNodeV2,
    context: RolePromptPreparationContextV2,
    *,
    stage_digest: str,
    recipe_digest: str,
) -> bool:
    """Old complete single-Main proofs need no migration or paid model bootstrap."""

    if "prepared_character_prompt" in node.metadata:
        return False
    presentation = node.prompt_presentation
    parent = context.character_identity_projection
    if (
        context.role_variant != "character_turnaround"
        or parent is None
        or len(context.bindings) != 1
        or presentation is None
        or not node.generation_prompt
        or presentation.source not in {"agent_authored", "deterministic_projection"}
        or presentation.text != node.generation_prompt
    ):
        return False
    try:
        saved = LegacyCharacterPromptProofV1.model_validate(
            node.metadata.get("retained_legacy_character_prompt")
        )
        old_parent = saved.parent
        original_identity = CharacterIdentityAuthorityProjectionV1.build(
            **parent.model_dump(
                mode="json",
                exclude={
                    "source_node_revision",
                    "source_asset_id",
                    "source_asset_version_id",
                    "projection_digest",
                },
            ),
            source_node_revision=old_parent.source_node_revision,
            source_asset_id=old_parent.asset_id if old_parent.asset_version_id else None,
            source_asset_version_id=old_parent.asset_version_id,
        )
    except ValidationError:
        return False
    reference_lineage = {"source_node_revision", "asset_id", "asset_version_id"}
    return (
        saved.stage_digest == stage_digest
        and saved.recipe_digest == recipe_digest
        and saved.node_inputs_digest == _node_inputs_digest(node)
        and saved.content_digest == _digest(node.structured_content)
        and saved.prompt_digest
        == presentation.prompt_digest
        == f"sha256:{sha256(node.generation_prompt.encode('utf-8')).hexdigest()}"
        and saved.brief_digest == presentation.brief_digest
        and old_parent.model_dump(exclude=reference_lineage)
        == context.bindings[0].model_dump(exclude=reference_lineage)
        and original_identity.projection_digest
        == node.structured_content.get("identity_projection_digest")
    )


def _node_inputs_digest(node: CanvasNodeV2) -> str:
    return _digest(
        {
            "summary_prompt": node.summary_prompt,
            "parameters": node.parameters,
            "model_ref": node.model_ref,
            "model_selection_mode": node.model_selection_mode,
            "occurrence_id": node.metadata.get("occurrence_id"),
            "character_phase": node.metadata.get("character_phase"),
            "requirement_revision_id": node.metadata.get("requirement_revision_id"),
            "requirement_revision_no": node.metadata.get("requirement_revision_no"),
        }
    )


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"
