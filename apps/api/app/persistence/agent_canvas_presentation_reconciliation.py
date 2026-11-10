"""Derive prompt delivery endings from persisted Node authority, never elapsed time."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from app.schemas.agent_canvas_presentation import PresentationStreamEventV1


def prompt_terminal_event(
    stream: Mapping[str, Any], node: Mapping[str, Any]
) -> PresentationStreamEventV1 | None:
    preparation = json.loads(node["prompt_preparation_json"])
    fields: dict[str, Any] = {}
    if preparation.get("operation_id") != stream["generation_id"]:
        # Creation precedes the Node's working transition. Equal revisions can
        # describe a new stream not yet attached to its Node; leave it alone.
        if node["revision"] <= stream["node_revision"]:
            return None
        event_type = "superseded"
    elif preparation.get("status") == "ready" and node["generation_prompt"]:
        event_type = "committed"
        fields = {
            "authoritative_id": f"{node['node_id']}:{node['revision']}",
            "content_digest": sha256(node["generation_prompt"].encode("utf-8")).hexdigest(),
        }
    elif preparation.get("status") == "failed":
        event_type = "failed"
        fields = {"error_code": "prompt_preparation_failed"}
    elif preparation.get("status") == "superseded":
        event_type = "superseded"
    else:
        return None
    return PresentationStreamEventV1(
        stream_id=stream["stream_id"],
        workflow_id=stream["workflow_id"],
        stream_kind="node_prompt",
        generation_id=stream["generation_id"],
        node_id=stream["node_id"],
        node_revision=stream["node_revision"],
        sequence_no=stream["last_sequence_no"] + 1,
        event_type=event_type,
        **fields,
    )
