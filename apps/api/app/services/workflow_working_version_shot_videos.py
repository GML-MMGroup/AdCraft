from copy import deepcopy
from pathlib import Path
from typing import Any

from app.services.media_paths import with_public_urls
from app.services.workflow_asset_history import load_node_asset_history
from app.services.workflow_item_prompt_utils import item_id_from_payload
from app.services.workflow_state import resolve_active_result
from app.services import workflow_working_version_enrichment as wv_enrichment
from app.services import workflow_working_version_items as wv_items
from app.services import workflow_working_version_store as wv_store


def shot_video_generation_status(
    shot: dict[str, Any],
    video_item: dict[str, Any] | None,
) -> dict[str, Any]:
    shot_id = item_id_from_payload(shot)
    if (
        shot_id
        and video_item
        and not video_item.get("needs_apply")
        and video_item.get("selected_version")
    ):
        return {"shot_id": shot_id, "status": "skipped", "reason": "clean"}
    return {"shot_id": shot_id, "status": "needs_generation"}


def resolve_storyboard_shot(data_dir: Path, workflow_id: str, shot_id: str) -> dict[str, Any]:
    for shot in storyboard_shots(data_dir, workflow_id):
        if item_id_from_payload(shot) == shot_id:
            return shot
    raise ValueError(f"Storyboard shot not found: {shot_id}.")


def storyboard_shots(data_dir: Path, workflow_id: str) -> list[dict[str, Any]]:
    active = resolve_active_result(data_dir, workflow_id, "storyboard", "storyboard")
    if not active:
        return []
    output = active.get("output") if isinstance(active.get("output"), dict) else {}
    return wv_items.payload_items(output, "storyboard")


def storyboard_visual_assets(
    data_dir: Path,
    workflow_id: str,
    shot_id: str,
) -> list[dict[str, Any]]:
    assets = [
        asset
        for asset in load_node_asset_history(data_dir, workflow_id, "storyboard")
        if wv_items.asset_matches_item(asset, shot_id, "storyboard")
        and asset.get("is_active") is not False
        and wv_items.asset_uri(asset)
    ]
    if assets:
        return with_public_urls(assets)
    active = resolve_active_result(data_dir, workflow_id, "storyboard", "storyboard")
    if not active:
        return []
    return [
        asset
        for asset in active.get("output_assets", [])
        if isinstance(asset, dict)
        and wv_items.asset_matches_item(asset, shot_id, "storyboard")
        and wv_items.asset_uri(asset)
    ]


def ensure_video_node_output(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    active = resolve_active_result(
        data_dir,
        workflow_id,
        node_id,
        "storyboard-video-generation",
    )
    if active and isinstance(active.get("output"), dict):
        output = deepcopy(active["output"])
    else:
        output = {"structured_output": {"videoSegments": []}, "media_items": []}
    segments = wv_items.canonical_items(output, "storyboard-video-generation", create=True)
    item_id = item_id_from_payload(item)
    existing = next(
        (segment for segment in segments if item_id_from_payload(segment) == item_id), None
    )
    if existing is None:
        segments.append(item)
    else:
        existing.update({key: value for key, value in item.items() if value not in (None, "")})
    wv_items.sync_media_items(output, segments)
    wv_store.persist_node_output(data_dir, workflow_id, node_id, output, [])
    wv_store.save_graph_node_output(data_dir, workflow_id, node_id, output, [])
    return output


def video_item(data_dir: Path, workflow_id: str, shot_id: str) -> dict[str, Any] | None:
    active = resolve_active_result(
        data_dir,
        workflow_id,
        "storyboard-video-generation",
        "storyboard-video-generation",
    )
    if not active or not isinstance(active.get("output"), dict):
        return None
    output = wv_enrichment.enrich_output(
        data_dir,
        workflow_id,
        "storyboard-video-generation",
        "storyboard-video-generation",
        active["output"],
        active.get("output_assets") if isinstance(active.get("output_assets"), list) else [],
    )
    try:
        return wv_items.require_item(output, shot_id)
    except ValueError:
        return None
