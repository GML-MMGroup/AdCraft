import json
from pathlib import Path
from typing import Any

from app.services.media_paths import public_url_for_path, with_public_urls

STORYBOARD_VIDEO_NODE_ID = "storyboard-video-generation"
FINAL_VIDEO_ASSET_ID = "final-ad-video"
READY_DOWNLOAD_STATUSES = {"downloaded", "ready"}
FAILED_SEGMENT_STATUSES = {"failed", "error", "cancelled", "canceled"}


def load_workflow_segments(data_dir: Path, workflow_id: str) -> list[dict[str, Any]]:
    segment_dir = data_dir / "videos" / workflow_id / "segments"
    segments: list[dict[str, Any]] = []
    for metadata_path in segment_dir.glob("segment-*.json"):
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        payload.setdefault("metadata_path", metadata_path.relative_to(data_dir).as_posix())
        segments.append(_with_fresh_public_url(payload))
    segments.sort(key=lambda segment: int(segment.get("order") or 0))
    return segments


def segment_is_ready(data_dir: Path, segment: dict[str, Any]) -> bool:
    local_path = segment.get("local_path")
    return (
        isinstance(local_path, str)
        and bool(local_path)
        and segment.get("download_status") in READY_DOWNLOAD_STATUSES
        and (data_dir / local_path).exists()
    )


def segment_has_failed(segment: dict[str, Any]) -> bool:
    return str(segment.get("status") or "").lower() in FAILED_SEGMENT_STATUSES


def segment_readiness(data_dir: Path, segments: list[dict[str, Any]]) -> dict[str, Any]:
    ready_count = sum(1 for segment in segments if segment_is_ready(data_dir, segment))
    total_count = len(segments)
    all_ready = bool(segments) and ready_count == total_count
    return {
        "segments_ready": all_ready,
        "segments_waiting": bool(segments) and not all_ready,
        "ready_segment_count": ready_count,
        "total_segment_count": total_count,
    }


def segment_asset(data_dir: Path, segment: dict[str, Any]) -> dict[str, Any]:
    enriched = _with_fresh_public_url(segment)
    local_path = enriched.get("local_path")
    public_url = (
        public_url_for_path(local_path)
        if isinstance(local_path, str) and local_path.strip()
        else enriched.get("public_url")
    )
    asset_id = str(
        enriched.get("asset_id")
        or enriched.get("segment_id")
        or f"storyboard-video-segment-{enriched.get('order') or 1}"
    )
    return {
        **enriched,
        "asset_id": asset_id,
        "asset_type": "video",
        "type": "video",
        "media_type": "video",
        "kind": "video",
        "role": "video_segment",
        "source_node_id": STORYBOARD_VIDEO_NODE_ID,
        "local_path": local_path,
        "public_url": public_url,
        "download_status": enriched.get("download_status"),
        "order": enriched.get("order"),
        "duration_seconds": enriched.get("duration_seconds"),
        "metadata_path": enriched.get("metadata_path"),
        "is_ready": segment_is_ready(data_dir, enriched),
    }


def ready_segment_assets(data_dir: Path, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        segment_asset(data_dir, segment)
        for segment in segments
        if segment_is_ready(data_dir, segment)
    ]


def storyboard_video_status(data_dir: Path, segments: list[dict[str, Any]]) -> str:
    if not segments:
        return "not_started"
    if any(segment_has_failed(segment) for segment in segments):
        return "failed"
    if all(segment_is_ready(data_dir, segment) for segment in segments):
        return "ready"
    return "waiting_for_segments"


def storyboard_video_output_from_segments(
    data_dir: Path,
    workflow_id: str,
    segments: list[dict[str, Any]],
    existing_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = storyboard_video_status(data_dir, segments)
    output = dict(existing_output or {})
    output.update(
        {
            "provider": output.get("provider", "volcengine-storyboard-video-generation"),
            "asset_id": output.get("asset_id", STORYBOARD_VIDEO_NODE_ID),
            "segments": segments,
            "duration_seconds": output.get("duration_seconds")
            or sum(int(segment.get("duration_seconds") or 0) for segment in segments),
            "resolution": output.get("resolution") or _first_value(segments, "resolution"),
            "ratio": output.get("ratio") or _first_value(segments, "ratio"),
            "mime_type": output.get("mime_type", "video/mp4"),
            "status": status,
            "composition_status": "ready" if status == "ready" else "waiting_for_segments",
            "source_segments": [
                str(segment.get("asset_id")) for segment in segments if segment.get("asset_id")
            ],
            "metadata_source": f"videos/{workflow_id}/segments",
        }
    )
    return with_public_urls(output)


def final_composition_waiting_output(
    data_dir: Path,
    workflow_id: str,
    segments: list[dict[str, Any]],
    *,
    overwrite_ready: bool = True,
) -> dict[str, Any]:
    status = "waiting_for_segments" if segments else "not_started"
    composition_status = "waiting_for_segments" if segments else "not_started"
    return persist_final_composition_metadata(
        data_dir,
        workflow_id,
        {
            "workflow_id": workflow_id,
            "provider": "segment-metadata",
            "asset_id": FINAL_VIDEO_ASSET_ID,
            "source_asset": STORYBOARD_VIDEO_NODE_ID,
            "source_segments": [
                str(segment.get("asset_id")) for segment in segments if segment.get("asset_id")
            ],
            "duration_seconds": sum(
                int(segment.get("duration_seconds") or 0) for segment in segments
            ),
            "mime_type": "video/mp4",
            "operation": "wait for generated video segments before composition",
            "uses_llm_generation": False,
            "status": status,
            "composition_status": composition_status,
            "local_path": None,
            "metadata_path": f"final/{workflow_id}/final-ad-video.json",
            **segment_readiness(data_dir, segments),
        },
        overwrite_ready=overwrite_ready,
    )


def persist_final_composition_metadata(
    data_dir: Path,
    workflow_id: str,
    final_output: dict[str, Any],
    *,
    overwrite_ready: bool = True,
) -> dict[str, Any]:
    relative_metadata_path = f"final/{workflow_id}/final-ad-video.json"
    metadata_path = data_dir / relative_metadata_path
    existing = _read_json(metadata_path)
    incoming_status = str(final_output.get("status") or "not_started")
    if (
        not overwrite_ready
        and incoming_status != "ready"
        and _final_metadata_is_ready(data_dir, existing)
    ):
        existing.setdefault("metadata_path", relative_metadata_path)
        return with_public_urls(existing)

    payload = {
        **final_output,
        "workflow_id": workflow_id,
        "asset_id": FINAL_VIDEO_ASSET_ID,
        "status": incoming_status,
        "composition_status": final_output.get("composition_status")
        or ("ready" if incoming_status == "ready" else incoming_status),
        "source_asset": final_output.get("source_asset") or STORYBOARD_VIDEO_NODE_ID,
        "source_segments": final_output.get("source_segments") or [],
        "duration_seconds": final_output.get("duration_seconds") or 0,
        "local_path": final_output.get("local_path"),
        "metadata_path": relative_metadata_path,
        "segments_ready": bool(final_output.get("segments_ready")),
        "segments_waiting": bool(final_output.get("segments_waiting")),
        "ready_segment_count": int(final_output.get("ready_segment_count") or 0),
        "total_segment_count": int(final_output.get("total_segment_count") or 0),
    }
    _write_json(metadata_path, payload)
    return with_public_urls(payload)


def sync_storyboard_video_run_with_segments(
    data_dir: Path,
    workflow_id: str,
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    segments = segments if segments is not None else load_workflow_segments(data_dir, workflow_id)
    active_path = (
        data_dir / "runs" / workflow_id / "nodes" / STORYBOARD_VIDEO_NODE_ID / "active.json"
    )
    if not active_path.exists():
        return None
    payload = json.loads(active_path.read_text(encoding="utf-8"))
    output = storyboard_video_output_from_segments(
        data_dir,
        workflow_id,
        segments,
        existing_output=payload.get("output") if isinstance(payload.get("output"), dict) else {},
    )
    output_assets = ready_segment_assets(data_dir, segments)
    payload["output"] = output
    payload["output_assets"] = output_assets
    payload["status"] = "failed" if output.get("status") == "failed" else "completed"
    if isinstance(payload.get("trace"), dict):
        payload["trace"]["output"] = output
        payload["trace"]["output_assets"] = output_assets
    _write_json(active_path, payload)
    trace_path = payload.get("trace_path") or payload.get("metadata_path")
    if isinstance(trace_path, str):
        run_path = data_dir / trace_path
        if run_path.exists() and run_path != active_path:
            _write_json(run_path, payload)
    _sync_graph_node(data_dir, workflow_id, payload)
    return payload


def _first_value(segments: list[dict[str, Any]], key: str) -> Any:
    for segment in segments:
        value = segment.get(key)
        if value not in (None, ""):
            return value
    return None


def _with_fresh_public_url(segment: dict[str, Any]) -> dict[str, Any]:
    enriched = with_public_urls(segment)
    local_path = enriched.get("local_path")
    if isinstance(local_path, str) and local_path.strip():
        enriched["public_url"] = public_url_for_path(local_path)
    return enriched


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _final_metadata_is_ready(data_dir: Path, payload: dict[str, Any]) -> bool:
    local_path = payload.get("local_path")
    return (
        str(payload.get("status") or "").lower() == "ready"
        and isinstance(local_path, str)
        and bool(local_path.strip())
        and (data_dir / local_path).exists()
    )


def _sync_graph_node(data_dir: Path, workflow_id: str, payload: dict[str, Any]) -> None:
    from app.services.workflow_graph import update_graph_node_from_run_result

    update_graph_node_from_run_result(
        data_dir=data_dir,
        workflow_id=workflow_id,
        node_id=STORYBOARD_VIDEO_NODE_ID,
        result=payload,
    )
