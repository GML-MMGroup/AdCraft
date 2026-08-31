"""Shared persisted target validation for guided reference checkpoints."""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import ValidationError

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
