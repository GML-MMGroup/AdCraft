"""Typed Tianpuyue instrumental-provider primitives for V2 BGM."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.tianpuyue_pure_music import (
    TianpuyueInstrumentalGenerateRequest,
    TianpuyueInstrumentalGenerateResponse,
    TianpuyueInstrumentalModelSelection,
    TianpuyueInstrumentalQueryRequest,
    TianpuyueInstrumentalQueryResponse,
)
from app.services.tianpuyue_callback_lease import TianpuyueCallbackLeaseError
from app.services.v2_data_boundary import validate_v2_data_path
from app.tools.media_provider_protocol import MediaConfigurationError


TIANPUYUE_BGM_HOST = "api.tianpuyue.cn"
TIANPUYUE_SHORT_DURATION_LIMIT_SECONDS = 120
TIANPUYUE_LONG_DURATION_LIMIT_SECONDS = 270
TIANPUYUE_SUCCESS_STATUS = 200000
TIANPUYUE_INSTRUMENTAL_SUBMIT_PATH = "/open-apis/v1/instrumental/generate"
TIANPUYUE_INSTRUMENTAL_QUERY_PATH = "/open-apis/v1/instrumental/query"
_MAX_DIAGNOSTIC_ITEM_IDS = 8
_MAX_DIAGNOSTIC_ITEM_ID_LENGTH = 128
_MAX_SAFE_ERROR_MESSAGE_LENGTH = 2_048
_URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)\b(?P<key>authorization|api[_-]?key|access[_-]?key|token|secret|signature)"
    r"\s*(?:=|:)\s*(?:bearer\s+)?[^\s,;\"'}\]]+"
)
_RETRYABLE_PROVIDER_STATUSES = {400001, 400006, 400007}
_PROVIDER_ERROR_CODES = {
    400001: "bgm_provider_busy",
    400002: "bgm_provider_auth_failed",
    400003: "bgm_provider_request_invalid",
    400004: "bgm_provider_content_rejected",
    400005: "bgm_provider_quota_exhausted",
    400006: "bgm_provider_busy",
    400007: "bgm_provider_busy",
    400008: "bgm_provider_task_missing",
    400009: "bgm_provider_task_failed",
    400010: "bgm_provider_model_unsupported",
}


class TianpuyuePureMusicError(ValueError):
    def __init__(self, code: str, message: str, *, metadata: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = metadata


def select_tianpuyue_instrumental_model(
    duration_seconds: int,
    settings: Settings,
) -> TianpuyueInstrumentalModelSelection:
    if duration_seconds < 1 or duration_seconds > TIANPUYUE_LONG_DURATION_LIMIT_SECONDS:
        raise TianpuyuePureMusicError(
            "bgm_duration_unsupported",
            "Tianpuyue instrumental generation supports durations from 1 to 270 seconds.",
            metadata={
                "requested_duration_seconds": duration_seconds,
                "minimum_duration_seconds": 1,
                "maximum_duration_seconds": TIANPUYUE_LONG_DURATION_LIMIT_SECONDS,
            },
        )
    if duration_seconds <= TIANPUYUE_SHORT_DURATION_LIMIT_SECONDS:
        model = str(settings.bgm_model or "").strip()
        duration_limit_seconds = TIANPUYUE_SHORT_DURATION_LIMIT_SECONDS
    else:
        model = str(settings.bgm_long_model or "").strip()
        duration_limit_seconds = TIANPUYUE_LONG_DURATION_LIMIT_SECONDS
    if not model:
        raise MediaConfigurationError("Tianpuyue BGM model configuration is required.")
    return TianpuyueInstrumentalModelSelection(
        model=model,
        duration_limit_seconds=duration_limit_seconds,
    )


def validate_tianpuyue_bgm_settings(settings: Settings) -> None:
    endpoint = str(settings.bgm_endpoint or "").strip()
    parsed = urlparse(endpoint)
    if not str(settings.bgm_api_key or "").strip():
        raise MediaConfigurationError("Tianpuyue BGM provider requires BGM_API_KEY.")
    if parsed.scheme != "https" or parsed.hostname != TIANPUYUE_BGM_HOST:
        raise MediaConfigurationError(
            "Tianpuyue BGM_ENDPOINT must use the official https://api.tianpuyue.cn host."
        )
    select_tianpuyue_instrumental_model(1, settings)
    select_tianpuyue_instrumental_model(121, settings)


class TianpuyuePureMusicAdapter:
    """Tianpuyue instrumental adapter configured for V2 BGM work."""

    def __init__(
        self,
        settings: Settings,
        data_dir: Path,
        *,
        client: httpx.Client | None = None,
        callback_id_factory: Callable[[], str] | None = None,
        callback_base_url_resolver: Callable[[], str] | None = None,
        audio_probe: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._data_dir = data_dir
        self._validate_settings()
        mode = str(settings.bgm_callback_mode or "").strip().lower()
        if callback_base_url_resolver is None:
            if mode != "manual":
                raise MediaConfigurationError(
                    "Automatic Tianpuyue callbacks must be built through the BGM provider factory."
                )

            def resolve_manual_callback_base_url() -> str:
                return str(settings.bgm_callback_base_url or "")

            callback_base_url_resolver = resolve_manual_callback_base_url
        self._callback_base_url_resolver = callback_base_url_resolver
        self._client = client or httpx.Client(timeout=settings.bgm_timeout_seconds)
        self._owns_client = client is None
        self._callback_id_factory = callback_id_factory or _new_callback_id
        self._audio_probe = audio_probe or self._probe_audio

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
            return self._failure(
                "bgm_provider_output_invalid",
                "Tianpuyue BGM provider prompt is required.",
                stage="submit",
            )
        duration_seconds = _duration_seconds(bgm_plan.get("duration_seconds"))
        try:
            selection = select_tianpuyue_instrumental_model(duration_seconds, self._settings)
        except TianpuyuePureMusicError as exc:
            return self._failure(exc.code, str(exc), stage="submit", **exc.metadata)
        try:
            callback_id, callback_url = self._callback_details(workflow_id)
        except TianpuyueCallbackLeaseError as exc:
            return self._failure(
                exc.code,
                str(exc),
                stage="callback_lease",
                retryable=exc.retryable,
            )
        request_body = TianpuyueInstrumentalGenerateRequest(
            prompt=_instrumental_prompt(prompt, duration_seconds),
            model=selection.model,
            callback_url=callback_url,
        ).model_dump(exclude_none=True)
        response, failure = self._post_json(
            TIANPUYUE_INSTRUMENTAL_SUBMIT_PATH,
            request_body,
            stage="submit",
        )
        if failure is not None:
            return failure
        assert response is not None
        payload = _json_object(response)
        if payload is None:
            return self._failure(
                "bgm_provider_submission_uncertain",
                "Tianpuyue BGM submission returned an unreadable response.",
                stage="submit",
                retryable=False,
            )
        try:
            envelope = TianpuyueInstrumentalGenerateResponse.model_validate(payload)
        except ValidationError:
            return self._failure(
                "bgm_provider_submission_uncertain",
                "Tianpuyue BGM submission response did not match the documented envelope.",
                stage="submit",
                retryable=False,
                request_id=_request_id(payload),
            )
        if envelope.status != TIANPUYUE_SUCCESS_STATUS:
            return self._provider_failure(
                envelope.status,
                envelope.message,
                request_id=envelope.request_id,
                stage="submit",
            )
        item_ids = _bounded_item_ids(envelope.data.item_ids if envelope.data else [])
        if not item_ids:
            return self._failure(
                "bgm_provider_output_invalid",
                "Tianpuyue BGM submission did not include a non-empty item id.",
                stage="submit",
                request_id=envelope.request_id,
            )
        return self._asset(
            status="submitted",
            task_id=item_ids[0],
            model=selection.model,
            requested_duration_seconds=duration_seconds,
            model_duration_limit_seconds=selection.duration_limit_seconds,
            request_id=envelope.request_id,
            callback_id=callback_id,
            callback_enabled=callback_url is not None,
            additional_item_ids=item_ids[1:],
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
        response, failure = self._post_json(
            TIANPUYUE_INSTRUMENTAL_QUERY_PATH,
            TianpuyueInstrumentalQueryRequest(item_ids=[remote_task_id]).model_dump(),
            stage="query",
        )
        if failure is not None:
            return self._query_failure_or_waiting(remote_task_id, failure)
        assert response is not None
        payload = _json_object(response)
        if payload is None:
            return self._waiting(
                remote_task_id,
                "Tianpuyue BGM query returned an unreadable response.",
                waiting_reason="retryable_provider_query_error",
                error_code="bgm_provider_output_invalid",
            )
        try:
            envelope = TianpuyueInstrumentalQueryResponse.model_validate(payload)
        except ValidationError:
            return self._waiting(
                remote_task_id,
                "Tianpuyue BGM query response did not match the documented envelope.",
                waiting_reason="retryable_provider_query_error",
                error_code="bgm_provider_output_invalid",
                request_id=_request_id(payload),
            )
        if envelope.status != TIANPUYUE_SUCCESS_STATUS:
            if envelope.status == 400008 and not _expired_reconciliation_started(provider_payload):
                return self._waiting(
                    remote_task_id,
                    envelope.message or "Tianpuyue BGM work is not visible yet.",
                    waiting_reason="provider_task_missing_grace",
                    error_code="bgm_provider_task_missing",
                    request_id=envelope.request_id,
                )
            failure = self._provider_failure(
                envelope.status,
                envelope.message,
                request_id=envelope.request_id,
                stage="query",
                remote_task_id=remote_task_id,
            )
            if envelope.status == 400008:
                return failure
            return self._query_failure_or_waiting(remote_task_id, failure)
        records = envelope.data.instrumentals if envelope.data else []
        record = next((entry for entry in records if entry.item_id == remote_task_id), None)
        if record is None:
            if _expired_reconciliation_started(provider_payload):
                return self._failure(
                    "bgm_provider_task_missing",
                    "Tianpuyue BGM query did not include the requested item id after final reconciliation.",
                    remote_task_id=remote_task_id,
                    stage="query",
                    retryable=False,
                    request_id=envelope.request_id,
                )
            return self._waiting(
                remote_task_id,
                "Tianpuyue BGM query did not include the requested item id.",
                waiting_reason="provider_task_missing_grace",
                error_code="bgm_provider_task_missing",
                request_id=envelope.request_id,
            )
        metadata = {
            "requested_duration_seconds": _duration_seconds(
                provider_payload.get("duration_seconds")
            ),
            "provider_status": record.status,
            "provider_model": record.model,
            "provider_duration_seconds": record.duration,
            "request_id": envelope.request_id,
            "workflow_id": workflow_id,
        }
        normalized_status = str(record.status or "").strip().lower()
        if normalized_status in {"failed", "cancelled", "canceled", "abnormal"}:
            return self._failure(
                "bgm_provider_task_failed",
                "Tianpuyue BGM task reached a terminal failure state.",
                remote_task_id=remote_task_id,
                stage="query",
                **metadata,
            )
        if normalized_status not in {"succeeded", "completed", "success"}:
            return self._waiting(
                remote_task_id,
                "Tianpuyue BGM task is still running.",
                waiting_reason="provider_task_still_running",
                **metadata,
            )
        audio_url = _first_nonempty(record.audio_hi_url, record.audio_url)
        if audio_url is None:
            return self._waiting(
                remote_task_id,
                "Tianpuyue BGM task completed without a usable audio URL yet.",
                waiting_reason="provider_audio_not_ready",
                **metadata,
            )
        metadata["selected_audio_url_path"] = _sanitized_url_path(audio_url)
        metadata["audio_quality"] = "high" if _first_nonempty(record.audio_hi_url) else "standard"
        if not download_media:
            return self._asset(
                status="submitted",
                task_id=remote_task_id,
                model=record.model,
                **metadata,
            )
        return self._download_audio(
            audio_url,
            remote_task_id=remote_task_id,
            model=record.model,
            **metadata,
        )

    def _validate_settings(self) -> None:
        validate_tianpuyue_bgm_settings(self._settings)

    def _callback_details(self, workflow_id: str) -> tuple[str, str]:
        base_url = str(self._callback_base_url_resolver() or "").strip()
        if not base_url:
            raise MediaConfigurationError(
                "Tianpuyue callback base URL resolver returned an empty URL."
            )
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise MediaConfigurationError(
                "Tianpuyue callback base URL must be an absolute HTTPS URL."
            )
        callback_id = str(self._callback_id_factory()).strip()
        if not callback_id:
            raise MediaConfigurationError("BGM callback id factory returned an empty id.")
        callback_url = (
            f"{base_url.rstrip('/')}/api/v2/provider-callbacks/tianpuyue/"
            f"instrumental/{workflow_id}/{callback_id}"
        )
        return callback_id, callback_url

    def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        stage: str,
    ) -> tuple[httpx.Response | None, dict[str, Any] | None]:
        try:
            response = self._client.post(
                _endpoint(self._settings.bgm_endpoint, path),
                json=payload,
                headers={"Authorization": str(self._settings.bgm_api_key)},
                timeout=self._settings.bgm_timeout_seconds,
            )
        except httpx.ConnectError:
            return None, self._failure(
                "bgm_provider_busy",
                "Tianpuyue BGM connection could not be established.",
                stage=stage,
                retryable=True,
            )
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError):
            return None, self._failure(
                "bgm_provider_submission_uncertain" if stage == "submit" else "bgm_provider_busy",
                "Tianpuyue BGM request did not complete reliably.",
                stage=stage,
                retryable=False if stage == "submit" else True,
            )
        except httpx.HTTPError:
            return None, self._failure(
                "bgm_provider_submission_uncertain" if stage == "submit" else "bgm_provider_busy",
                "Tianpuyue BGM request could not be completed.",
                stage=stage,
                retryable=False if stage == "submit" else True,
            )
        if response.status_code >= 500:
            return None, self._failure(
                "bgm_provider_busy",
                f"Tianpuyue BGM request returned HTTP {response.status_code}.",
                stage=stage,
                retryable=True,
            )
        if response.status_code >= 400:
            code = (
                "bgm_provider_auth_failed"
                if response.status_code in {401, 403}
                else "bgm_provider_request_invalid"
            )
            return None, self._failure(
                code,
                f"Tianpuyue BGM request returned HTTP {response.status_code}.",
                stage=stage,
                retryable=False,
            )
        return response, None

    def _provider_failure(
        self,
        provider_status: int,
        message: str | None,
        *,
        request_id: str | None,
        stage: str,
        remote_task_id: str | None = None,
    ) -> dict[str, Any]:
        code = _PROVIDER_ERROR_CODES.get(provider_status, "bgm_provider_output_invalid")
        return self._failure(
            code,
            message or "Tianpuyue BGM provider returned an error.",
            stage=stage,
            provider_status=provider_status,
            request_id=request_id,
            remote_task_id=remote_task_id,
            retryable=provider_status in _RETRYABLE_PROVIDER_STATUSES or provider_status == 400008,
        )

    def _query_failure_or_waiting(
        self,
        remote_task_id: str,
        failure: dict[str, Any],
    ) -> dict[str, Any]:
        if failure.get("metadata", {}).get("retryable"):
            metadata = dict(failure.get("metadata") or {})
            metadata.pop("remote_task_id", None)
            return self._waiting(
                remote_task_id,
                str(failure.get("error") or "Tianpuyue BGM query can be retried."),
                waiting_reason="retryable_provider_query_error",
                error_code=str(failure.get("error_code") or "bgm_provider_busy"),
                **metadata,
            )
        return failure

    def _waiting(
        self,
        remote_task_id: str,
        message: str,
        *,
        waiting_reason: str,
        error_code: str | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        return self._asset(
            status="submitted",
            task_id=remote_task_id,
            waiting_reason=waiting_reason,
            error_code=error_code,
            waiting_message=message,
            **metadata,
        )

    def _download_audio(
        self,
        audio_url: str,
        *,
        remote_task_id: str,
        model: str | None,
        **metadata: Any,
    ) -> dict[str, Any]:
        parsed = urlparse(audio_url)
        if parsed.scheme != "https" or not parsed.netloc:
            return self._download_failure(
                "Tianpuyue BGM output URL must use HTTPS.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=False,
                download_attempted=False,
                **metadata,
            )
        workflow_id = str(metadata.get("workflow_id") or "").strip()
        if not workflow_id:
            return self._download_failure(
                "Tianpuyue BGM output does not have a workflow owner.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=False,
                download_attempted=False,
                **metadata,
            )
        temporary_path: Path | None = None
        try:
            with self._client.stream(
                "GET",
                audio_url,
                timeout=self._settings.bgm_timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    return self._download_failure(
                        f"Tianpuyue BGM audio download returned HTTP {response.status_code}.",
                        remote_task_id=remote_task_id,
                        model=model,
                        retryable=response.status_code in {408, 429} or response.status_code >= 500,
                        download_attempted=True,
                        download_http_status=response.status_code,
                        **metadata,
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                extension = _audio_extension(content_type, parsed.path)
                if extension is None:
                    return self._download_failure(
                        "Tianpuyue BGM output media type is unsupported.",
                        remote_task_id=remote_task_id,
                        model=model,
                        retryable=False,
                        download_attempted=True,
                        **metadata,
                    )
                declared_size = _content_length(response.headers.get("content-length"))
                if (
                    declared_size is not None
                    and declared_size > self._settings.bgm_download_max_bytes
                ):
                    return self._download_failure(
                        "Tianpuyue BGM audio download exceeded the configured size limit.",
                        remote_task_id=remote_task_id,
                        model=model,
                        retryable=False,
                        download_attempted=True,
                        download_expected_bytes=declared_size,
                        **metadata,
                    )
                relative_path = (
                    Path("assets")
                    / "provider-output"
                    / workflow_id
                    / f"{_safe_file_stem(remote_task_id)}{extension}"
                )
                output_path = self._data_dir / relative_path
                validate_v2_data_path(
                    self._data_dir,
                    output_path,
                    operation="v2-tianpuyue-bgm-download",
                )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
                written_bytes = 0
                prefix = bytearray()
                with temporary_path.open("xb") as output:
                    for chunk in response.iter_bytes():
                        written_bytes += len(chunk)
                        if written_bytes > self._settings.bgm_download_max_bytes:
                            temporary_path.unlink(missing_ok=True)
                            return self._download_failure(
                                "Tianpuyue BGM audio download exceeded the configured size limit.",
                                remote_task_id=remote_task_id,
                                model=model,
                                retryable=False,
                                download_attempted=True,
                                download_received_bytes=written_bytes,
                                **metadata,
                            )
                        if len(prefix) < 64:
                            prefix.extend(chunk[: 64 - len(prefix)])
                        output.write(chunk)
        except (httpx.HTTPError, OSError):
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            return self._download_failure(
                "Tianpuyue BGM audio download could not be completed.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=True,
                download_attempted=True,
                **metadata,
            )
        if temporary_path is None or not temporary_path.exists():
            return self._download_failure(
                "Tianpuyue BGM audio download did not produce a temporary file.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=True,
                download_attempted=True,
                **metadata,
            )
        if temporary_path.stat().st_size == 0 or _looks_like_non_audio(bytes(prefix), content_type):
            temporary_path.unlink(missing_ok=True)
            return self._download_failure(
                "Tianpuyue BGM output was empty or not usable audio media.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=False,
                download_attempted=True,
                **metadata,
            )
        try:
            probe = self._audio_probe(temporary_path)
        except Exception as exc:  # noqa: BLE001 - a probe failure is invalid provider media.
            temporary_path.unlink(missing_ok=True)
            return self._failure(
                "bgm_audio_invalid",
                f"Tianpuyue BGM output could not be probed: {exc}",
                remote_task_id=remote_task_id,
                model=model,
                **metadata,
            )
        if probe.get("error") or not probe.get("has_audio"):
            temporary_path.unlink(missing_ok=True)
            return self._failure(
                "bgm_audio_invalid",
                "Tianpuyue BGM output is not a decodable audio stream.",
                remote_task_id=remote_task_id,
                model=model,
                **metadata,
            )
        output_path = self._data_dir / relative_path
        temporary_path.replace(output_path)
        return self._asset(
            status="ready",
            task_id=remote_task_id,
            model=model,
            local_path=relative_path.as_posix(),
            download_status="downloaded",
            download_attempted=True,
            source_content_type=content_type,
            source_extension=extension,
            duration_seconds=probe.get("duration_seconds"),
            audio_codec=probe.get("audio_codec"),
            sample_rate=probe.get("sample_rate"),
            channels=probe.get("channels"),
            **metadata,
        )

    def _probe_audio(self, path: Path) -> dict[str, Any]:
        command = [
            self._settings.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,sample_rate,channels",
            "-of",
            "json",
            path.as_posix(),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._settings.bgm_timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"error": str(exc)[:500], "has_audio": False}
        if completed.returncode != 0:
            return {"error": completed.stderr[:500], "has_audio": False}
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"error": "ffprobe returned invalid JSON", "has_audio": False}
        streams = payload.get("streams") if isinstance(payload, dict) else None
        audio_stream = next(
            (
                stream
                for stream in streams or []
                if isinstance(stream, dict) and stream.get("codec_type") == "audio"
            ),
            None,
        )
        if not isinstance(audio_stream, dict):
            return {"error": "ffprobe did not find an audio stream", "has_audio": False}
        format_payload = payload.get("format") if isinstance(payload, dict) else {}
        return {
            "has_audio": True,
            "duration_seconds": _float_or_none(
                format_payload.get("duration") if isinstance(format_payload, dict) else None
            ),
            "audio_codec": _string_or_none(audio_stream.get("codec_name")),
            "sample_rate": _int_or_none(audio_stream.get("sample_rate")),
            "channels": _int_or_none(audio_stream.get("channels")),
        }

    def _asset(
        self,
        *,
        status: str,
        task_id: str | None,
        model: str | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        safe_metadata = _safe_metadata(metadata)
        return {
            "provider": "tianpuyue",
            "model": model,
            "asset_id": "bgm-audio",
            "status": status,
            "task_id": task_id,
            "metadata": safe_metadata,
            **{
                key: value
                for key, value in safe_metadata.items()
                if value is not None and key not in {"workflow_id", "waiting_message"}
            },
        }

    def _failure(self, code: str, message: str, **metadata: Any) -> dict[str, Any]:
        return {
            "provider": "tianpuyue",
            "asset_id": "bgm-audio",
            "status": "failed",
            "error_code": code,
            "error": _safe_error_message(message),
            "metadata": _safe_metadata(metadata),
        }

    def _download_failure(
        self,
        message: str,
        *,
        remote_task_id: str,
        model: str | None,
        retryable: bool,
        download_attempted: bool,
        **metadata: Any,
    ) -> dict[str, Any]:
        return self._asset(
            status="failed",
            task_id=remote_task_id,
            model=model,
            error_code="bgm_audio_download_failed",
            error=message,
            download_status="failed",
            download_error_code="bgm_audio_download_failed",
            download_retryable=retryable,
            download_attempted=download_attempted,
            **metadata,
        )


def _duration_seconds(value: object) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        return 0
    return duration


def _instrumental_prompt(prompt: str, duration_seconds: int) -> str:
    return (
        f"{prompt.strip()}\n\n"
        f"Target duration: {duration_seconds} seconds. Instrumental only: no vocals, no lyrics, "
        "no narration, no spoken dialogue, and no sound effects."
    )


def _endpoint(base_url: str | None, path: str) -> str:
    return f"{str(base_url or '').rstrip('/')}{path}"


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _request_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("request_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bounded_item_ids(values: list[str]) -> list[str]:
    return [value.strip()[:_MAX_DIAGNOSTIC_ITEM_ID_LENGTH] for value in values if value.strip()][
        :_MAX_DIAGNOSTIC_ITEM_IDS
    ]


def _first_nonempty(*values: str | None) -> str | None:
    return next(
        (value.strip() for value in values if isinstance(value, str) and value.strip()), None
    )


def _sanitized_url_path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path[:512] if parsed.path else "/"


def _expired_reconciliation_started(provider_payload: dict[str, Any]) -> bool:
    value = provider_payload.get("expired_remote_reconciliation")
    return isinstance(value, dict) and bool(value.get("started_at"))


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_metadata_value(value)
        for key, value in metadata.items()
        if value is not None and not _is_forbidden_metadata_key(key)
    }


def _safe_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _safe_metadata(value)
    if isinstance(value, list):
        return [_safe_metadata_value(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_metadata_value(item) for item in value]
    if isinstance(value, str):
        return _safe_error_message(value)
    return value


def _is_forbidden_metadata_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized
        in {
            "api_key",
            "authorization",
            "callback_url",
            "audio_url",
            "audio_hi_url",
            "remote_url",
            "url",
        }
        or normalized.endswith("_api_key")
        or normalized.endswith("_authorization")
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
    )


def _safe_error_message(message: str) -> str:
    without_urls = _URL_PATTERN.sub("[redacted-url]", str(message))
    redacted = _SENSITIVE_TEXT_PATTERN.sub(
        lambda match: f"{match.group('key')}=[redacted]",
        without_urls,
    )
    return redacted[:_MAX_SAFE_ERROR_MESSAGE_LENGTH]


def _content_length(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _looks_like_non_audio(content: bytes, content_type: str) -> bool:
    normalized = content.lstrip().lower()
    return (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/xml", "text/html"}
        or normalized.startswith((b"<html", b"<!doctype", b"{", b"["))
    )


def _audio_extension(content_type: str, url_path: str) -> str | None:
    by_content_type = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/aac": ".aac",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/ogg": ".ogg",
    }
    if content_type in by_content_type:
        return by_content_type[content_type]
    suffix = Path(url_path).suffix.lower()
    return suffix if suffix in set(by_content_type.values()) else None


def _safe_file_stem(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-" for character in value
    )
    normalized = normalized.strip("-_")[:96]
    if normalized:
        return normalized
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _new_callback_id() -> str:
    from uuid import uuid4

    return f"callback_{uuid4().hex}"
