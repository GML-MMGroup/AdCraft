"""Shared persisted target validation for guided reference checkpoints."""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.persistence.errors import V2PersistenceError
from app.persistence.models import AssetEntityRow, AssetEntityMemberRow
from app.schemas.agent_canvas_guided_product import GuidedProductAssetVersionRefV1

from app.schemas.agent_canvas_guided_interactions import GuidedReferenceKindV1
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1


def reference_target_is_current(
    row: Mapping[str, object] | None,
    *,
    reference_kind: GuidedReferenceKindV1,
    target_node_revision: int,
    occurrence_id: str | None,
) -> bool:
    """Return whether one persisted Main Draft still owns the reference wait."""

    expected_role = "character" if reference_kind == "character_main" else "scene"
    if (
        row is None
        or str(row["node_type"]) != "image"
        or str(row["creative_role"]) != expected_role
        or str(row["execution_mode"]) != "generative"
        or int(row["revision"]) != target_node_revision
        or str(row["status"]) != "draft"
    ):
        return False
    try:
        metadata = json.loads(str(row["metadata_json"]))
        preparation = NodePromptPreparationV1.model_validate_json(
            str(row["prompt_preparation_json"])
        )
    except (TypeError, json.JSONDecodeError, ValidationError):
        return False
    if not isinstance(metadata, dict) or preparation.status != "queued":
        return False
    if reference_kind == "scene_main":
        return occurrence_id is None
    return bool(
        occurrence_id
        and metadata.get("occurrence_id") == occurrence_id
        and metadata.get("character_phase") in {None, "main"}
    )


def require_source_catalog_member(
    connection: Connection,
    reference: GuidedProductAssetVersionRefV1,
    *,
    source_role: str,
) -> None:
    """Check exact catalog membership both before compilation and at publication."""
    semantic_type = {
        "character": "character_three_view",
        "scene": "scene_multi_view_grid",
    }.get(source_role)
    member = connection.execute(
        select(AssetEntityMemberRow.member_id)
        .join(AssetEntityRow, AssetEntityRow.entity_id == AssetEntityMemberRow.entity_id)
        .where(
            AssetEntityRow.entity_id == reference.entity_id,
            AssetEntityRow.status == "active",
            AssetEntityRow.scope == ("user" if reference.source_scope == "mine" else "recommended"),
            AssetEntityMemberRow.member_id == reference.member_id,
            AssetEntityMemberRow.asset_id == reference.asset_id,
            AssetEntityMemberRow.version_id == reference.version_id,
            AssetEntityMemberRow.semantic_type == semantic_type,
        )
    ).scalar_one_or_none()
    if semantic_type is None or member is None:
        raise V2PersistenceError(
            "reference_candidate_not_found",
            "The selected library image is unavailable or its identity has changed. Select it again.",
            stage="guided_source_validation",
        )
