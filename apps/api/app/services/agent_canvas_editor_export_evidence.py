"""Read saved browser-editor delivery facts without inferring them from video titles."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math

from app.schemas.agent_canvas import CanvasNodeV2


@dataclass(frozen=True)
class SavedEditorExport:
    asset_id: str
    snapshot_digest: str
    has_unexported_changes: bool

    @property
    def export_id(self) -> str:
        identity = f"{self.asset_id}:{self.snapshot_digest}"
        return "editor_export_" + sha256(identity.encode()).hexdigest()[:32]


def saved_editor_export(node: CanvasNodeV2) -> SavedEditorExport | None:
    """A saved export is a historical delivery, even after later timeline edits."""
    if node.node_type != "editing":
        return None
    try:
        state = node.parameters["cutia_editor_v1"]
        snapshot, exported = state["snapshot"], state["export"]
        project = snapshot["project"]
        if snapshot["schemaVersion"] != 1 or project["metadata"]["id"] != (
            f"{node.workflow_id}:{node.node_id}"
        ):
            return None
        asset_id = exported["assetId"]
        if not isinstance(asset_id, str) or not asset_id or len(asset_id) > 160:
            return None
        rendered = json.loads(exported["snapshotKey"])
        media = {item["id"]: item["assetId"] for item in rendered["media"]}
        scene = next(
            item for item in rendered["scenes"] if item["id"] == rendered["currentSceneId"]
        )
        if not any(
            element["type"] == "video"
            and element.get("mediaId") in media
            and isinstance(element.get("duration"), (int, float))
            and math.isfinite(element["duration"])
            and element["duration"] > 0
            for track in scene["tracks"]
            for element in track["elements"]
        ):
            return None
        current = {
            "scenes": [{"id": item["id"], "tracks": item["tracks"]} for item in project["scenes"]],
            "currentSceneId": project["currentSceneId"],
            "settings": project["settings"],
            "media": [{"id": item["id"], "assetId": item["assetId"]} for item in snapshot["media"]],
        }
        digest = sha256(
            json.dumps(rendered, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        return SavedEditorExport(asset_id, digest, current != rendered)
    except (KeyError, TypeError, ValueError, StopIteration, AttributeError):
        return None
