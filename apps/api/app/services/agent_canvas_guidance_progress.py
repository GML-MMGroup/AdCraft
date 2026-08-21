"""Safe activity and semantic progress snapshots for guided production."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas.agent_canvas_guidance import GuidanceProgressSnapshotV1


class GuidanceProgressSnapshotService:
    """Hash public projections while separating liveness from authoring progress."""

    def snapshot(
        self,
        workflow: dict[str, Any],
        timeline: dict[str, Any],
        *,
        event_cursor: int | None = None,
    ) -> GuidanceProgressSnapshotV1:
        guidance = timeline.get("guidance_session") or {}
        journey = guidance.get("journey") or {}
        items = list(timeline.get("items") or ())
        continuations = list(timeline.get("continuations") or ())
        activity = {
            "event_cursor": event_cursor,
            "latest_entry_id": items[-1].get("entry_id") if items else None,
            "latest_entry_sequence": items[-1].get("sequence_no") if items else None,
            "continuations": sorted(
                [
                    str(item.get("continuation_id") or ""),
                    str(item.get("status") or ""),
                    int(item.get("attempt_count") or 0),
                ]
                for item in continuations
            ),
        }
        decision_bundle = next(
            (
                {
                    "bundle_id": (item.get("metadata") or {}).get("bundle_id"),
                    "status": (item.get("metadata") or {}).get("status"),
                    "revision": (item.get("metadata") or {}).get("revision"),
                }
                for item in reversed(items)
                if item.get("entry_type") == "decision_bundle"
                and (item.get("metadata") or {}).get("status") == "open"
            ),
            None,
        )
        semantic = {
            "workflow_revision": workflow.get("revision"),
            "guidance_revision": guidance.get("revision"),
            "journey_stage": journey.get("stage"),
            "journey_stage_revision": journey.get("stage_revision"),
            "journey_stage_status": journey.get("stage_status") or journey.get("status"),
            "journey_active_action": journey.get("active_action"),
            "active_proposal_id": guidance.get("active_proposal_id"),
            "active_decision_bundle": decision_bundle,
            "nodes": sorted(
                [
                    str(node.get("node_id") or ""),
                    node.get("revision"),
                    str(node.get("status") or ""),
                ]
                for node in workflow.get("nodes") or ()
            ),
            "bindings": sorted(
                [
                    str(binding.get("binding_id") or ""),
                    str(binding.get("source_node_id") or ""),
                    str(binding.get("target_node_id") or ""),
                    bool(binding.get("enabled", True)),
                ]
                for binding in workflow.get("bindings") or ()
            ),
        }
        return GuidanceProgressSnapshotV1(
            activity_token=_token(activity),
            semantic_progress_token=_token(semantic),
            activity_components=activity,
            semantic_components=semantic,
        )


def _token(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
