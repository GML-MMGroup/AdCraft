"""Run one bounded, credentialed Agent Canvas acceptance workflow.

This operator command never prints prompts, credentials, provider payloads, or
absolute paths. It stops before creating a project when required real provider
capabilities are unavailable.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

import httpx


TERMINAL_TURN = {"completed", "failed"}
TERMINAL_EXECUTION = {"completed", "partial_failed", "failed", "cancelled"}
REQUIRED_ROLES = {
    "product_main",
    "product_view_board",
    "scene_design_board",
    "storyboard_grid",
    "storyboard_video_segment",
}


class SmokeBlocked(RuntimeError):
    """A structured environment or lifecycle block."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--through", choices=("runtime", "editing"), default="editing")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args()


class Client:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=30)

    def close(self) -> None:
        self._client.close()

    def get(self, path: str) -> tuple[dict[str, Any], httpx.Headers]:
        response = self._client.get(path)
        self._require_success(response)
        return response.json(), response.headers

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        etag: str | None = None,
    ) -> tuple[dict[str, Any], httpx.Headers]:
        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if etag:
            headers["If-Match"] = etag
        response = self._client.post(path, json=body, headers=headers)
        self._require_success(response)
        return response.json(), response.headers

    @staticmethod
    def _require_success(response: httpx.Response) -> None:
        if response.is_success:
            return
        code = f"http_{response.status_code}"
        message = "Agent Canvas smoke request failed."
        try:
            detail = response.json().get("detail", {})
            if isinstance(detail, dict):
                code = str(detail.get("code") or code)
                message = str(detail.get("message") or message)
        except (ValueError, AttributeError):
            pass
        raise SmokeBlocked(code, message)


def _wait(
    load,
    *,
    terminal,
    deadline: float,
    description: str,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        value = load()
        if terminal(value):
            return value
        time.sleep(2)
    raise SmokeBlocked("smoke_timeout", f"Timed out waiting for {description}.")


def _preflight(client: Client) -> dict[str, Any]:
    health, _ = client.get("/api/v2/health")
    capabilities: dict[str, list[dict[str, Any]]] = {}
    for output_type in ("image", "video"):
        payload, _ = client.get(f"/api/v2/provider-models/capabilities?output_type={output_type}")
        items = list(payload.get("items") or [])
        if not items:
            raise SmokeBlocked(
                f"{output_type}_provider_unavailable",
                f"No configured real {output_type} provider capability is available.",
            )
        capabilities[output_type] = [
            {
                "provider": item.get("provider"),
                "model_id": item.get("model_id"),
                "available": item.get("available"),
            }
            for item in items
        ]
    return {
        "health": {
            "status": health.get("status"),
            "service": health.get("service"),
            "version": health.get("version"),
        },
        "capabilities": capabilities,
    }


def _submit_chat_plan(
    client: Client,
    workflow_id: str,
    *,
    deadline: float,
    run_id: str,
) -> dict[str, Any]:
    accepted, _ = client.post(
        f"/api/v2/workflows/{workflow_id}/chat/messages",
        {
            "text": (
                "Create a concise 15-second product advertisement. Materialize one "
                "product main image and view board, one scene design board, one "
                "storyboard grid, one storyboard video segment, optional BGM, and "
                "an Editing node. Use explicit bindings between every dependency."
            ),
            "auto_continue": True,
        },
        idempotency_key=f"{run_id}-chat",
    )
    turn_id = str(accepted["turn_id"])
    turn = _wait(
        lambda: client.get(f"/api/v2/workflows/{workflow_id}/chat/turns/{turn_id}")[0],
        terminal=lambda value: value.get("status") in TERMINAL_TURN,
        deadline=deadline,
        description="Director turn",
    )
    if turn.get("status") != "completed":
        raise SmokeBlocked(
            str(turn.get("error_code") or "director_turn_failed"),
            str(turn.get("error_message") or "Director turn failed."),
        )
    return {"turn_id": turn_id, "status": turn["status"]}


def _run_canvas(
    client: Client,
    workflow_id: str,
    *,
    deadline: float,
    run_id: str,
) -> dict[str, Any]:
    workflow, _ = client.get(f"/api/v2/workflows/{workflow_id}")
    roles = {str(node["semantic_role"]) for node in workflow.get("nodes", [])}
    missing = sorted(REQUIRED_ROLES - roles)
    if missing:
        raise SmokeBlocked(
            "smoke_required_drafts_missing",
            f"Director did not materialize required Draft roles: {', '.join(missing)}.",
        )
    accepted, _ = client.post(
        f"/api/v2/workflows/{workflow_id}/runs",
        {"scope": "all_drafts", "node_ids": [], "source_action": "run_all"},
        idempotency_key=f"{run_id}-run",
    )
    execution_id = str(accepted["execution_id"])
    runtime = _wait(
        lambda: client.get(f"/api/v2/workflows/{workflow_id}/runtime")[0],
        terminal=lambda value: value.get("execution_status") in TERMINAL_EXECUTION,
        deadline=deadline,
        description="Agent Canvas execution",
    )
    if runtime.get("execution_status") not in {"completed", "partial_failed"}:
        raise SmokeBlocked(
            "smoke_execution_failed",
            f"Agent Canvas execution ended as {runtime.get('execution_status')}.",
        )
    return {
        "execution_id": execution_id,
        "status": runtime.get("execution_status"),
        "events_cursor": runtime.get("events_cursor"),
    }


def _export_editing(
    client: Client,
    workflow_id: str,
    *,
    deadline: float,
    run_id: str,
) -> dict[str, Any]:
    workflow, _ = client.get(f"/api/v2/workflows/{workflow_id}")
    editing = next(
        (node for node in workflow.get("nodes", []) if node.get("node_type") == "editing"),
        None,
    )
    if editing is None:
        raise SmokeBlocked("smoke_editing_node_missing", "Editing node is missing.")
    node_id = str(editing["node_id"])
    detail, _ = client.get(f"/api/v2/workflows/{workflow_id}/nodes/{node_id}")
    manifest = detail.get("structured_content", {}).get("manifest", {})
    accepted, _ = client.post(
        f"/api/v2/workflows/{workflow_id}/nodes/{node_id}/export",
        {
            "expected_manifest_revision": manifest.get("manifest_revision"),
            "availability_policy": "use_ready_inputs",
        },
        idempotency_key=f"{run_id}-export",
    )
    completed = _wait(
        lambda: client.get(f"/api/v2/workflows/{workflow_id}/nodes/{node_id}")[0],
        terminal=lambda value: (
            value.get("status") in {"ready", "failed"}
            and value.get("structured_content", {}).get("active_export") is None
        ),
        deadline=deadline,
        description="Editing Export",
    )
    if completed.get("status") != "ready" or not completed.get("output_asset_id"):
        raise SmokeBlocked("smoke_editing_export_failed", "Editing Export did not complete.")
    return {
        "node_id": node_id,
        "export_id": accepted.get("export_id"),
        "status": completed.get("status"),
        "output_asset_id": completed.get("output_asset_id"),
    }


def main() -> int:
    args = _arguments()
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    run_id = f"agent-canvas-smoke-{uuid4().hex[:12]}"
    report: dict[str, Any] = {
        "contract": "agent-canvas-real-smoke-v1",
        "run_id": run_id,
        "started_at": now.isoformat(),
        "through": args.through,
        "status": "running",
    }
    client = Client(args.base_url)
    try:
        report["preflight"] = _preflight(client)
        project, _ = client.post(
            "/api/v2/projects",
            {"name": f"Agent Canvas smoke {now:%Y-%m-%d}"},
            idempotency_key=f"{run_id}-project",
        )
        workflow_id = str(project["workflow_id"])
        report["project_id"] = project.get("project_id")
        report["workflow_id"] = workflow_id
        deadline = time.monotonic() + args.timeout_seconds
        report["conversation"] = _submit_chat_plan(
            client, workflow_id, deadline=deadline, run_id=run_id
        )
        report["runtime"] = _run_canvas(client, workflow_id, deadline=deadline, run_id=run_id)
        if args.through == "editing":
            report["editing"] = _export_editing(
                client, workflow_id, deadline=deadline, run_id=run_id
            )
        assets, _ = client.get(f"/api/v2/workflows/{workflow_id}/assets")
        report["assets"] = [
            {
                "asset_id": item.get("asset_id"),
                "media_type": item.get("media_type"),
                "status": item.get("status"),
                "media_url": item.get("media_url"),
                "duration_seconds": item.get("duration_seconds"),
            }
            for item in assets.get("assets", [])
        ]
        events, _ = client.get(f"/api/v2/workflows/{workflow_id}/events?limit=500")
        report["provider_tasks"] = [
            {
                "event_type": item.get("event_type"),
                "node_id": item.get("node_id"),
                "provider_task_id": item.get("payload", {}).get("provider_task_id"),
            }
            for item in events.get("items", [])
            if item.get("event_type", "").startswith("provider_task_")
        ]
        report["status"] = "completed"
        return_code = 0
    except (SmokeBlocked, httpx.HTTPError) as error:
        report["status"] = "blocked" if isinstance(error, SmokeBlocked) else "failed"
        report["error"] = {
            "code": getattr(error, "code", "smoke_transport_failed"),
            "message": str(error),
        }
        return_code = 2
    finally:
        client.close()
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"status": report["status"], "report": str(args.report)}))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
