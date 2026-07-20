from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.core.config import Settings
from app.tools.media_provider_protocol import MediaConfigurationError


class LegacyBgmAdapter:
    """V1 compatibility adapter for the deprecated bearer-token BGM contract."""

    def __init__(self, settings: Settings, data_dir: Path) -> None:
        self._settings = settings
        self._data_dir = data_dir
        if not settings.bgm_api_key or not settings.bgm_endpoint:
            raise MediaConfigurationError(
                "Real BGM provider requires BGM_API_KEY and BGM_ENDPOINT."
            )

    def generate_bgm_audio(
        self,
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        response = self._post_json(self._settings.bgm_endpoint or "", _legacy_bgm_payload(bgm_plan))
        return self._asset_from_response(response, workflow_id, bgm_plan)

    def retrieve_bgm_audio_task(
        self,
        remote_task_id: str,
        *,
        workflow_id: str,
        provider_payload: dict[str, Any],
        download_media: bool = True,
    ) -> dict[str, Any]:
        endpoint = (
            self._settings.bgm_query_endpoint
            or str(provider_payload.get("task_query_url") or "")
            or self._settings.bgm_endpoint
            or ""
        )
        response = self._post_json(
            endpoint.replace("{task_id}", remote_task_id),
            {"task_id": remote_task_id},
        )
        return self._asset_from_response(
            response,
            workflow_id,
            provider_payload,
            fallback_task_id=remote_task_id,
            download_media=download_media,
        )

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not endpoint:
            raise MediaConfigurationError("Real BGM provider requires BGM_ENDPOINT.")
        request = urllib_request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._settings.bgm_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(
                request,
                timeout=self._settings.bgm_timeout_seconds,
            ) as response:
                body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            message = exc.read().decode("utf-8", "replace")
            raise ValueError(f"BGM provider request failed: {exc.code} {message}") from exc
        return json.loads(body) if body else {}

    def _asset_from_response(
        self,
        response: dict[str, Any],
        workflow_id: str,
        provider_payload: dict[str, Any],
        *,
        fallback_task_id: str | None = None,
        download_media: bool = True,
    ) -> dict[str, Any]:
        payload = _legacy_response_payload(response)
        status = _legacy_status(payload)
        task_id = _first_string(payload, ("task_id", "taskId", "TaskId", "id")) or fallback_task_id
        audio_url = _first_string(
            payload,
            ("audio_url", "audioUrl", "url", "download_url", "tos_url", "tos_uri", "output_url"),
        )
        asset: dict[str, Any] = {
            "provider": self._settings.bgm_provider,
            "model": self._settings.bgm_model,
            "asset_id": "bgm-audio",
            "task_id": task_id,
            "task_query_url": _first_string(payload, ("task_query_url", "query_url")),
            "status": status,
            "remote_url": audio_url,
            "provider_payload": _safe_payload(provider_payload),
            "raw_response": _safe_payload(payload),
        }
        if status in {"failed", "error"}:
            asset.update(
                {
                    "status": "failed",
                    "error_code": _first_string(payload, ("error_code", "code"))
                    or "provider_generation_failed",
                    "error": _first_string(payload, ("error_message", "message", "error"))
                    or "BGM provider task failed.",
                }
            )
            return asset
        if audio_url and download_media:
            relative_path = Path("assets") / "provider-output" / workflow_id / "bgm.mp3"
            output_path = self._data_dir / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with urllib_request.urlopen(
                audio_url,
                timeout=self._settings.bgm_timeout_seconds,
            ) as response:
                output_path.write_bytes(response.read())
            asset.update(
                {
                    "status": "ready",
                    "local_path": relative_path.as_posix(),
                    "download_status": "downloaded",
                }
            )
            return asset
        if audio_url:
            asset.update({"status": "ready", "remote_url": audio_url})
            return asset
        if task_id:
            asset.update({"status": "submitted"})
            return asset
        asset.update(
            {
                "status": "failed",
                "error_code": "provider_output_missing",
                "error": "BGM provider response did not include audio output or task id.",
            }
        )
        return asset


def _legacy_bgm_payload(bgm_plan: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "prompt": bgm_plan.get("prompt") or bgm_plan.get("provider_prompt"),
        "duration_seconds": bgm_plan.get("duration_seconds"),
        "negative_constraints": bgm_plan.get("negative_constraints"),
        "ad_tone": bgm_plan.get("ad_tone"),
        "brand_emotion": bgm_plan.get("brand_emotion"),
        "pace": bgm_plan.get("pace"),
        "music_mood": bgm_plan.get("music_mood"),
        "energy": bgm_plan.get("energy"),
        "instrumentation": bgm_plan.get("instrumentation"),
        "commercial_pacing": bgm_plan.get("commercial_pacing"),
        "audio_constraints": bgm_plan.get("audio_constraints"),
        "loop_behavior": bgm_plan.get("loop_behavior"),
        "model": bgm_plan.get("model"),
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def _legacy_response_payload(response: dict[str, Any]) -> dict[str, Any]:
    for key in ("data", "result", "Result", "ResponseMetadata"):
        value = response.get(key)
        if isinstance(value, dict):
            return {**response, **value}
    return response


def _legacy_status(payload: dict[str, Any]) -> str:
    status = str(
        payload.get("status")
        or payload.get("task_status")
        or payload.get("TaskStatus")
        or payload.get("state")
        or ""
    ).lower()
    if status in {"success", "succeeded", "completed", "done", "ready"}:
        return "ready"
    if status in {"failed", "error"}:
        return "failed"
    if status in {"running", "submitted", "queued", "pending", "processing"}:
        return "submitted"
    return status or "submitted"


def _first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted_keys = {"api_key", "authorization", "token", "secret", "access_key", "secret_key"}
    return {
        key: "[REDACTED]" if key.lower() in redacted_keys else value
        for key, value in payload.items()
    }
