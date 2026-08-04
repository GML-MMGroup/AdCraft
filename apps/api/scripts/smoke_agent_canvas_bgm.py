"""Run one serial real BGM smoke through the public Agent Canvas API.

The backend process supplies credentials from its configured environment. This
script never reads or prints credential values, provider payloads, callback
URLs, or raw provider responses.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload, {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as error:
        detail: dict[str, Any] = {}
        try:
            detail = json.loads(error.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        code = str(detail.get("detail", {}).get("code") or f"http_{error.code}")
        raise RuntimeError(f"Agent Canvas request failed: {code}") from error


def _asset_duration_seconds(content: bytes) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            "pipe:0",
        ],
        input=content,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe rejected the published BGM asset.")
    payload = json.loads(result.stdout.decode("utf-8"))
    duration = float(payload["format"]["duration"])
    if duration <= 0:
        raise RuntimeError("Published BGM duration must be non-zero.")
    return duration


def _canonical_asset_file_exists(data_dir: Path, *, started_at: float) -> bool:
    asset_root = data_dir / "assets"
    return any(
        path.is_file() and path.stat().st_mtime >= started_at for path in asset_root.rglob("*")
    )


def run_smoke(
    *,
    base_url: str,
    data_dir: Path,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    started_at = time.time()
    nonce = uuid4().hex[:12]
    project, project_headers = _request(
        base_url,
        "/api/v2/projects",
        method="POST",
        body={"name": "BGM provider smoke"},
        headers={"Idempotency-Key": f"bgm-smoke-project-{nonce}"},
    )
    workflow_id = str(project["workflow_id"])
    node_response, _ = _request(
        base_url,
        f"/api/v2/workflows/{workflow_id}/nodes",
        method="POST",
        body={
            "node_type": "audio",
            "creative_role": "general_audio",
            "title": "BGM provider smoke",
            "generation_prompt": "Create a short instrumental background track with no vocals.",
            "parameters": {"duration_seconds": 10},
            "position": {"x": 0, "y": 0},
        },
        headers={"If-Match": project_headers["etag"]},
    )
    node_id = str(node_response["node"]["node_id"])
    accepted, _ = _request(
        base_url,
        f"/api/v2/workflows/{workflow_id}/runs",
        method="POST",
        body={
            "scope": "selected_nodes",
            "node_ids": [node_id],
            "source_action": "global_run",
        },
        headers={"Idempotency-Key": f"bgm-smoke-run-{nonce}"},
    )
    execution_id = str(accepted["execution_id"])
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        workflow, _ = _request(base_url, f"/api/v2/workflows/{workflow_id}")
        node = next(item for item in workflow["nodes"] if item["node_id"] == node_id)
        if node["status"] == "ready":
            asset_id = str(node["output_asset_id"])
            content_request = urllib.request.Request(
                f"{base_url.rstrip('/')}/api/v2/assets/{asset_id}/content",
                headers={"Accept": "audio/*"},
            )
            with urllib.request.urlopen(content_request, timeout=30) as response:
                content = response.read()
            duration_seconds = _asset_duration_seconds(content)
            if not _canonical_asset_file_exists(data_dir, started_at=started_at):
                raise RuntimeError(
                    "No newly published canonical media file was found under data/assets."
                )
            events, _ = _request(base_url, f"/api/v2/workflows/{workflow_id}/events")
            return {
                "workflow_id": workflow_id,
                "execution_id": execution_id,
                "node_id": node_id,
                "asset_id": asset_id,
                "duration_seconds": duration_seconds,
                "event_types": [str(item["event_type"]) for item in events["items"]],
            }
        if node["status"] == "failed":
            error = node.get("error") or {}
            raise RuntimeError(
                f"Agent Canvas Audio Node failed: {error.get('code', 'node_failed')}"
            )
        time.sleep(poll_interval_seconds)
    raise TimeoutError(
        "Timed out while waiting for the Agent Canvas Audio Node to become terminal."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-interval-seconds", type=float, default=8.0)
    args = parser.parse_args()
    result = run_smoke(
        base_url=args.base_url,
        data_dir=args.data_dir,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
