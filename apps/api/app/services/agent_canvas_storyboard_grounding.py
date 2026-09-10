"""Build and validate the immutable storyboard-grid grounding projection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from app.schemas.agent_canvas import CanvasNodeV2, ResolvedMediaInputSnapshotV2
from app.schemas.agent_canvas_ad_media import StoryboardGridContentV2
from app.schemas.seedance_inputs import (
    StoryboardGridGroundingPlanV1,
    StoryboardGroundingReferenceV1,
    StoryboardPanelReferenceV1,
)


class GroundingPlanError(ValueError):
    """Stable pre-submit error raised for an invalid storyboard authority."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def build_storyboard_grid_grounding_plan(
    *,
    node: CanvasNodeV2,
    grid_input: ResolvedMediaInputSnapshotV2 | None,
    storyboard_content: StoryboardGridContentV2 | Mapping[str, Any],
    target_shot_id: str,
    prompt_snapshot: str,
    ordered_references: Sequence[StoryboardGroundingReferenceV1 | Mapping[str, Any]],
    provider_reference_limit: int,
    expected_version_id: str | None = None,
    expected_checksum: str | None = None,
    expected_storyboard_revision: str | None = None,
) -> StoryboardGridGroundingPlanV1:
    """Derive one version-pinned plan from explicit binding and saved grid data."""

    if grid_input is None or grid_input.media_type != "image":
        raise GroundingPlanError("v2_storyboard_grid_reference_missing")
    if grid_input.source_semantic_role not in {"storyboard_grid", "storyboard_sequence"}:
        raise GroundingPlanError("v2_storyboard_grid_reference_missing")
    version_id = grid_input.asset_version_id
    if not version_id or (expected_version_id is not None and version_id != expected_version_id):
        raise GroundingPlanError("v2_storyboard_grid_reference_stale")
    if expected_checksum is not None and grid_input.asset_checksum != expected_checksum:
        raise GroundingPlanError("v2_storyboard_grid_reference_stale")
    metadata = grid_input.binding_metadata
    revision = _required_string(metadata.get("storyboard_revision"))
    if revision is None:
        raise GroundingPlanError("v2_storyboard_grid_reference_stale")
    if expected_storyboard_revision is not None and revision != expected_storyboard_revision:
        raise GroundingPlanError("v2_storyboard_grid_reference_stale")
    try:
        content = (
            storyboard_content
            if isinstance(storyboard_content, StoryboardGridContentV2)
            else StoryboardGridContentV2.model_validate(storyboard_content)
        )
    except ValidationError as error:
        raise GroundingPlanError("v2_storyboard_grid_panel_mapping_invalid") from error
    if len(content.panels) != 9 or [panel.panel_index for panel in content.panels] != list(
        range(1, 10)
    ):
        raise GroundingPlanError("v2_storyboard_grid_panel_mapping_invalid")

    panel_shots = metadata.get("panel_shots")
    if panel_shots is None:
        panel_shots = [target_shot_id] * 9
    if not isinstance(panel_shots, (list, tuple)) or len(panel_shots) != 9:
        raise GroundingPlanError("v2_storyboard_grid_panel_mapping_invalid")
    if any(str(shot_id) != target_shot_id for shot_id in panel_shots):
        raise GroundingPlanError("v2_storyboard_grid_panel_mapping_invalid")

    panels = tuple(
        StoryboardPanelReferenceV1(
            panel_index=panel.panel_index,
            shot_id=target_shot_id,
            beat=panel.beat,
        )
        for panel in content.panels
    )
    grid_reference = StoryboardGroundingReferenceV1(
        asset_id=grid_input.asset_id,
        version_id=version_id,
        checksum=grid_input.asset_checksum,
        semantic_role="storyboard_grid",
        binding_id=grid_input.binding_id or f"asset:{grid_input.asset_id}",
        display_order=0,
    )
    references = tuple(
        _reference_from_input(item, display_order=index)
        for index, item in enumerate(ordered_references, start=1)
    )
    identities = {(item.asset_id, item.version_id) for item in (grid_reference, *references)}
    if len(identities) != len((grid_reference, *references)):
        raise GroundingPlanError("v2_storyboard_grid_panel_mapping_invalid")
    if len(references) + 1 > provider_reference_limit:
        required_count = sum(item.required for item in references) + 1
        if required_count > provider_reference_limit:
            raise GroundingPlanError("v2_storyboard_grid_reference_limit_exceeded")
        references = tuple(item for item in references if item.required)
    ordered = (grid_reference, *references)
    panel_fingerprint = _digest(
        [
            {"panel_index": item.panel_index, "shot_id": item.shot_id, "beat": item.beat}
            for item in panels
        ]
    )
    prompt_digest = hashlib.sha256(prompt_snapshot.encode("utf-8")).hexdigest()
    plan_fingerprint = _digest(
        {
            "node_id": node.node_id,
            "grid_asset_id": grid_input.asset_id,
            "grid_version_id": version_id,
            "grid_checksum": grid_input.asset_checksum,
            "storyboard_revision": revision,
            "panel_sequence_fingerprint": panel_fingerprint,
            "provider_reference_limit": provider_reference_limit,
            "prompt_snapshot_digest": prompt_digest,
            "ordered_references": [item.model_dump(mode="json") for item in ordered],
        }
    )
    return StoryboardGridGroundingPlanV1(
        node_id=node.node_id,
        grid_asset_id=grid_input.asset_id,
        grid_version_id=version_id,
        grid_checksum=grid_input.asset_checksum,
        storyboard_revision=revision,
        panels=panels,
        target_shot_id=target_shot_id,
        target_panel_indices=tuple(range(1, 10)),
        ordered_references=ordered,
        provider_reference_limit=provider_reference_limit,
        prompt_snapshot_digest=prompt_digest,
        panel_sequence_fingerprint=panel_fingerprint,
        plan_fingerprint=plan_fingerprint,
    )


def _reference_from_input(
    value: StoryboardGroundingReferenceV1 | Mapping[str, Any],
    *,
    display_order: int,
) -> StoryboardGroundingReferenceV1:
    if isinstance(value, StoryboardGroundingReferenceV1):
        return value.model_copy(update={"display_order": display_order})
    try:
        payload = dict(value)
        payload.setdefault(
            "semantic_role", payload.get("source_semantic_role") or payload.get("role")
        )
        payload.setdefault(
            "binding_id", payload.get("binding_id") or f"binding:{payload.get('asset_id')}"
        )
        payload.setdefault("display_order", display_order)
        return StoryboardGroundingReferenceV1.model_validate(payload)
    except ValidationError as error:
        raise GroundingPlanError("v2_storyboard_grid_panel_mapping_invalid") from error


def _required_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
