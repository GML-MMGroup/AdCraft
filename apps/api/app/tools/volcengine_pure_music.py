"""Official Volcengine AI Music OpenAPI adapter for V2 background music."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.tools.media_provider_protocol import MediaConfigurationError
from app.tools.volcengine_openapi_signer import VolcengineOpenApiSigner


VOLCENGINE_BGM_HOST = "https://open.volcengineapi.com"
VOLCENGINE_BGM_REGION = "cn-beijing"
VOLCENGINE_BGM_SERVICE = "imagination"
VOLCENGINE_BGM_SUBMIT_ACTIONS = {"GenBGM", "GenBGMForTime"}
VOLCENGINE_BGM_QUERY_ACTION = "QuerySong"


class VolcengineResponseMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    request_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("RequestId", "RequestID"),
    )
    error: dict[str, Any] | None = Field(default=None, validation_alias="Error")


class VolcengineGenerateBgmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    text: str = Field(alias="Text")
    duration: int = Field(alias="Duration", ge=30, le=120)
    enable_input_rewrite: bool = Field(alias="EnableInputRewrite")
    version: str = Field(alias="Version", min_length=1)


class VolcengineQuerySongRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    task_id: str = Field(alias="TaskID", min_length=1)


class VolcengineSongDetail(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    audio_url: str | None = Field(default=None, validation_alias="AudioUrl")
    duration_seconds: float | None = Field(
        default=None,
        validation_alias=AliasChoices("Duration", "DurationSeconds"),
    )


class VolcengineTaskPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    task_id: str | None = Field(default=None, validation_alias="TaskID")
    status: int | None = Field(default=None, validation_alias="Status")
    progress: int | None = Field(default=None, validation_alias="Progress")
    song_detail: VolcengineSongDetail | None = Field(default=None, validation_alias="SongDetail")
    failure_reason: dict[str, Any] | None = Field(default=None, validation_alias="FailureReason")


class VolcengineApiEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    code: int | None = Field(default=None, validation_alias="Code")
    message: str | None = Field(default=None, validation_alias="Message")
    result: VolcengineTaskPayload | None = Field(default=None, validation_alias="Result")
    response_metadata: VolcengineResponseMetadata | None = Field(
        default=None,
        validation_alias="ResponseMetadata",
    )


class VolcenginePureMusicAdapter:
    """Submits and polls pure-music tasks through Volcengine OpenAPI."""

    def __init__(
        self,
        settings: Settings,
        data_dir: Path,
        *,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
        signer: VolcengineOpenApiSigner | None = None,
    ) -> None:
        self._settings = settings
        self._data_dir = data_dir
        self._validate_settings()
        self._client = client or httpx.Client(timeout=settings.bgm_timeout_seconds)
        self._owns_client = client is None
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._signer = signer or VolcengineOpenApiSigner()

    def __del__(self) -> None:
        if getattr(self, "_owns_client", False):
            self._client.close()

    def generate_bgm_audio(
        self,
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        prompt = str(bgm_plan.get("provider_prompt") or bgm_plan.get("prompt") or "").strip()
        if not prompt:
            return self._failure("bgm_provider_output_invalid", "BGM provider prompt is required.")
        requested_duration = _duration_seconds(bgm_plan.get("duration_seconds"))
        provider_duration = min(max(requested_duration, 30), 120)
        body = VolcengineGenerateBgmRequest(
            text=prompt,
            duration=provider_duration,
            enable_input_rewrite=False,
            version=self._settings.bgm_generation_version,
        ).model_dump(by_alias=True)
        envelope, failure = self._post_official(self._settings.bgm_submit_action, body)
        if failure is not None:
            return failure
        assert envelope is not None
        if envelope.code != 0:
            return self._api_failure(envelope, action=self._settings.bgm_submit_action)
        task_id = envelope.result.task_id if envelope.result is not None else None
        if not task_id or not task_id.strip():
            return self._failure(
                "bgm_provider_output_invalid",
                "Volcengine BGM submission did not include Result.TaskID.",
                action=self._settings.bgm_submit_action,
                request_id=_request_id(envelope),
            )
        return self._asset(
            status="submitted",
            task_id=task_id.strip(),
            requested_duration_seconds=requested_duration,
            provider_duration_seconds=provider_duration,
            provider_action=self._settings.bgm_submit_action,
            api_version=self._settings.bgm_api_version,
            generation_version=self._settings.bgm_generation_version,
            request_id=_request_id(envelope),
            workflow_id=workflow_id,
        )

    def retrieve_bgm_audio_task(
        self,
        remote_task_id: str,
        *,
        workflow_id: str,
        provider_payload: dict[str, Any],
        download_media: bool = True,
    ) -> dict[str, Any]:
        requested_duration = _duration_seconds(provider_payload.get("duration_seconds"))
        provider_duration = _duration_seconds(provider_payload.get("provider_duration_seconds"))
        provider_action = str(
            provider_payload.get("provider_action")
            or provider_payload.get("action")
            or self._settings.bgm_submit_action
        )
        envelope, failure = self._post_official(
            VOLCENGINE_BGM_QUERY_ACTION,
            VolcengineQuerySongRequest(task_id=remote_task_id).model_dump(by_alias=True),
        )
        if failure is not None:
            return failure
        assert envelope is not None
        if envelope.code != 0:
            return self._api_failure(envelope, action=VOLCENGINE_BGM_QUERY_ACTION)
        result = envelope.result
        if result is None or result.status is None:
            return self._failure(
                "bgm_provider_output_invalid",
                "Volcengine QuerySong response did not include Result.Status.",
                action=VOLCENGINE_BGM_QUERY_ACTION,
                request_id=_request_id(envelope),
            )
        base = {
            "task_id": remote_task_id,
            "requested_duration_seconds": requested_duration,
            "provider_duration_seconds": provider_duration,
            "provider_action": provider_action,
            "query_action": VOLCENGINE_BGM_QUERY_ACTION,
            "api_version": self._settings.bgm_api_version,
            "generation_version": self._settings.bgm_generation_version,
            "request_id": _request_id(envelope),
            "provider_status": result.status,
            "progress": result.progress,
            "workflow_id": workflow_id,
        }
        if result.status in {0, 1}:
            return self._asset(status="submitted", **base)
        if result.status == 3:
            reason = result.failure_reason or {}
            return self._failure(
                "bgm_provider_task_failed",
                _safe_failure_message(reason) or "Volcengine BGM task failed.",
                **base,
            )
        if result.status != 2:
            return self._failure(
                "bgm_provider_output_invalid",
                f"Volcengine QuerySong returned unsupported task status: {result.status}.",
                **base,
            )
        audio_url = result.song_detail.audio_url if result.song_detail is not None else None
        if not audio_url or not audio_url.strip():
            return self._failure(
                "bgm_provider_output_invalid",
                "Volcengine QuerySong success response did not include Result.SongDetail.AudioUrl.",
                **base,
            )
        base["audio_duration_seconds"] = (
            result.song_detail.duration_seconds if result.song_detail is not None else None
        )
        if not download_media:
            return self._asset(status="submitted", remote_url=audio_url, **base)
        return self._download_audio(audio_url, remote_task_id=remote_task_id, **base)

    def _validate_settings(self) -> None:
        endpoint = str(self._settings.bgm_endpoint or "").strip()
        parsed = urlparse(endpoint)
        if not self._settings.bgm_access_key_id or not self._settings.bgm_secret_access_key:
            raise MediaConfigurationError(
                "Real BGM provider requires BGM_ACCESS_KEY_ID and BGM_SECRET_ACCESS_KEY."
            )
        if parsed.scheme != "https" or parsed.hostname != "open.volcengineapi.com":
            raise MediaConfigurationError(
                "BGM_ENDPOINT must use the official https://open.volcengineapi.com host."
            )
        if self._settings.bgm_submit_action not in VOLCENGINE_BGM_SUBMIT_ACTIONS:
            raise MediaConfigurationError("BGM_SUBMIT_ACTION must be GenBGM or GenBGMForTime.")
        if not self._settings.bgm_api_version or not self._settings.bgm_generation_version:
            raise MediaConfigurationError(
                "BGM_API_VERSION and BGM_GENERATION_VERSION must not be empty."
            )

    def _post_official(
        self,
        action: str,
        body_payload: dict[str, Any],
    ) -> tuple[VolcengineApiEnvelope | None, dict[str, Any] | None]:
        body = json.dumps(body_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        query = (("Action", action), ("Version", self._settings.bgm_api_version))
        endpoint = _openapi_endpoint(str(self._settings.bgm_endpoint))
        signed = self._signer.sign(
            method="POST",
            endpoint=endpoint,
            query=query,
            body=body,
            access_key_id=str(self._settings.bgm_access_key_id),
            secret_access_key=str(self._settings.bgm_secret_access_key),
            timestamp=self._now(),
            region=VOLCENGINE_BGM_REGION,
            service=VOLCENGINE_BGM_SERVICE,
        )
        try:
            response = self._client.post(
                endpoint,
                params=query,
                content=body,
                headers=signed.headers,
                timeout=self._settings.bgm_timeout_seconds,
            )
        except httpx.HTTPError:
            return None, self._failure(
                "bgm_provider_http_error",
                "Volcengine BGM request could not be completed.",
                action=action,
            )
        payload = _json_object(response)
        request_id = _request_id_from_payload(payload)
        if response.status_code >= 400:
            code = (
                "bgm_provider_auth_failed"
                if response.status_code in {401, 403}
                else "bgm_provider_http_error"
            )
            return None, self._failure(
                code,
                f"Volcengine BGM request returned HTTP {response.status_code}.",
                action=action,
                request_id=request_id,
            )
        if payload is None:
            return None, self._failure(
                "bgm_provider_output_invalid",
                "Volcengine BGM response was not a JSON object.",
                action=action,
            )
        try:
            return VolcengineApiEnvelope.model_validate(payload), None
        except ValidationError:
            return None, self._failure(
                "bgm_provider_output_invalid",
                "Volcengine BGM response did not match the official response envelope.",
                action=action,
                request_id=request_id,
            )

    def _api_failure(self, envelope: VolcengineApiEnvelope, *, action: str) -> dict[str, Any]:
        metadata_error = envelope.response_metadata.error if envelope.response_metadata else None
        message = (
            _safe_failure_message(metadata_error)
            or envelope.message
            or "Volcengine BGM API failed."
        )
        error_code = "bgm_provider_api_error"
        error_value = str((metadata_error or {}).get("Code") or "").lower()
        if "auth" in error_value or "access" in error_value or "permission" in error_value:
            error_code = "bgm_provider_auth_failed"
        return self._failure(
            error_code,
            message,
            action=action,
            request_id=_request_id(envelope),
        )

    def _download_audio(
        self,
        audio_url: str,
        *,
        remote_task_id: str,
        **metadata: Any,
    ) -> dict[str, Any]:
        metadata.pop("task_id", None)
        parsed = urlparse(audio_url)
        if parsed.scheme != "https" or not parsed.netloc:
            return self._failure(
                "bgm_audio_download_failed",
                "Volcengine BGM output URL must use HTTPS.",
                **metadata,
            )
        try:
            with self._client.stream(
                "GET",
                audio_url,
                timeout=self._settings.bgm_timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    return self._failure(
                        "bgm_audio_download_failed",
                        f"Volcengine BGM audio download returned HTTP {response.status_code}.",
                        **metadata,
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                declared_size = _content_length(response.headers.get("content-length"))
                if (
                    declared_size is not None
                    and declared_size > self._settings.bgm_download_max_bytes
                ):
                    return self._failure(
                        "bgm_audio_download_failed",
                        "Volcengine BGM audio download exceeded the configured size limit.",
                        **metadata,
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > self._settings.bgm_download_max_bytes:
                        return self._failure(
                            "bgm_audio_download_failed",
                            "Volcengine BGM audio download exceeded the configured size limit.",
                            **metadata,
                        )
        except httpx.HTTPError:
            return self._failure(
                "bgm_audio_download_failed",
                "Volcengine BGM audio download could not be completed.",
                **metadata,
            )
        if not content or _looks_like_non_audio(bytes(content), content_type):
            return self._failure(
                "bgm_audio_download_failed",
                "Volcengine BGM output was empty or not usable audio media.",
                **metadata,
            )
        extension = _audio_extension(content_type, parsed.path)
        if extension is None:
            return self._failure(
                "bgm_audio_download_failed",
                "Volcengine BGM output media type is unsupported.",
                **metadata,
            )
        relative_path = (
            Path("assets")
            / "provider-output"
            / str(metadata["workflow_id"])
            / (f"{remote_task_id}{extension}")
        )
        output_path = self._data_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(bytes(content))
        return self._asset(
            status="ready",
            task_id=remote_task_id,
            local_path=relative_path.as_posix(),
            download_status="downloaded",
            source_content_type=content_type,
            source_extension=extension,
            **metadata,
        )

    def _asset(self, *, status: str, task_id: str | None = None, **metadata: Any) -> dict[str, Any]:
        return {
            "provider": self._settings.bgm_provider,
            "model": self._settings.bgm_generation_version,
            "asset_id": "bgm-audio",
            "status": status,
            "task_id": task_id,
            "metadata": _safe_metadata(metadata),
            **{
                key: value
                for key, value in metadata.items()
                if value is not None and key != "workflow_id"
            },
        }

    def _failure(self, code: str, message: str, **metadata: Any) -> dict[str, Any]:
        return {
            "provider": self._settings.bgm_provider,
            "model": self._settings.bgm_generation_version,
            "asset_id": "bgm-audio",
            "status": "failed",
            "error_code": code,
            "error": message,
            "metadata": _safe_metadata(metadata),
        }


def _duration_seconds(value: object) -> int:
    try:
        return max(1, int(float(value)))
    except (TypeError, ValueError):
        return 30


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _request_id(envelope: VolcengineApiEnvelope) -> str | None:
    return envelope.response_metadata.request_id if envelope.response_metadata else None


def _request_id_from_payload(payload: dict[str, Any] | None) -> str | None:
    metadata = payload.get("ResponseMetadata") if isinstance(payload, dict) else None
    if isinstance(metadata, dict):
        value = metadata.get("RequestId") or metadata.get("RequestID")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _safe_failure_message(reason: dict[str, Any] | None) -> str | None:
    if not isinstance(reason, dict):
        return None
    for key in ("Msg", "Message", "message"):
        value = reason.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    blocked = {"access_key_id", "secret_access_key", "authorization", "headers"}
    return {
        key: value
        for key, value in metadata.items()
        if key.lower() not in blocked and value is not None
    }


def _content_length(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _looks_like_non_audio(content: bytes, content_type: str) -> bool:
    normalized = content.lstrip().lower()
    return (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/problem+json", "text/html"}
        or normalized.startswith((b"<html", b"<!doctype html", b"{", b"["))
    )


def _audio_extension(content_type: str, url_path: str) -> str | None:
    by_content_type = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/wave": ".wav",
        "audio/aac": ".aac",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "audio/flac": ".flac",
    }
    if content_type in by_content_type:
        return by_content_type[content_type]
    suffix = Path(url_path).suffix.lower()
    return suffix if suffix in set(by_content_type.values()) else None


def _openapi_endpoint(endpoint: str) -> str:
    return endpoint.rstrip("/") + "/"
