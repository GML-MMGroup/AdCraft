from __future__ import annotations

import json
from typing import Any
from urllib import error as urllib_error

from app.tools.media_provider_protocol import MediaApiError


def _media_api_error(
    *,
    exc: urllib_error.HTTPError,
    endpoint: str,
    payload: dict[str, Any] | None,
) -> MediaApiError:
    response_body = exc.read().decode("utf-8", errors="replace")
    sanitized_payload = _sanitize_secret_values(payload)
    metadata = {
        "provider": "volcengine",
        "endpoint": endpoint,
        "status": exc.code,
        "response_body": response_body,
        "payload": sanitized_payload,
    }
    payload_json = json.dumps(sanitized_payload, ensure_ascii=False, indent=2, sort_keys=True)
    message = "\n".join(
        [
            "media_api_failed:",
            "provider=volcengine",
            f"endpoint={endpoint}",
            f"status={exc.code}",
            f"response_body={response_body}",
            f"payload={payload_json}",
        ]
    )
    return MediaApiError(message=message, metadata=metadata)


def _sanitize_secret_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redacted_value(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_secret_values(item) for item in value]
    return value


def _redacted_value(key: str, value: Any) -> Any:
    lowered_key = key.lower()
    if any(secret_key in lowered_key for secret_key in ("api_key", "apikey", "token", "secret")):
        return _redact_secret(str(value)) if value is not None else None
    if lowered_key == "authorization":
        return _redact_authorization(str(value)) if value is not None else None
    return _sanitize_secret_values(value)


def _redact_authorization(value: str) -> str:
    parts = value.split(maxsplit=1)
    if len(parts) == 2:
        return f"{parts[0]} {_redact_secret(parts[1])}"
    return _redact_secret(value)


def _redact_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _video_generation_task_id_from_response(response: dict[str, Any]) -> str:
    task_id = response.get("id") or response.get("task_id")
    if isinstance(task_id, str) and task_id.strip():
        return task_id

    data = response.get("data")
    if isinstance(data, dict):
        task_id = data.get("id") or data.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            return task_id

    raise ValueError("Volcengine video generation response did not include task id.")


def _optional_video_generation_task_id_from_response(response: dict[str, Any]) -> str | None:
    try:
        return _video_generation_task_id_from_response(response)
    except ValueError:
        return None


def _video_url_from_response(response: dict[str, Any]) -> str | None:
    if isinstance(response.get("url"), str):
        return response["url"]
    if isinstance(response.get("video_url"), str):
        return response["video_url"]
    output = response.get("output")
    if isinstance(output, dict) and isinstance(output.get("url"), str):
        return output["url"]
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("url"), str):
        return data["url"]
    content = response.get("content")
    if isinstance(content, dict):
        if isinstance(content.get("video_url"), str):
            return content["video_url"]
        if isinstance(content.get("url"), str):
            return content["url"]
    return None


def _video_resolution_from_response(response: dict[str, Any]) -> str | None:
    return _string_response_value(response, "resolution")


def _video_ratio_from_response(response: dict[str, Any]) -> str | None:
    return _string_response_value(response, "ratio") or _string_response_value(
        response,
        "aspect_ratio",
    )


def _video_duration_from_response(response: dict[str, Any]) -> int | None:
    value = _response_value(response, "duration") or _response_value(response, "duration_seconds")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _string_response_value(response: dict[str, Any], key: str) -> str | None:
    value = _response_value(response, key)
    return value if isinstance(value, str) and value.strip() else None


def _response_value(response: dict[str, Any], key: str) -> Any:
    if key in response:
        return response[key]
    for nested_key in ("content", "output", "data", "result"):
        nested = response.get(nested_key)
        if isinstance(nested, dict) and key in nested:
            return nested[key]
    return None


def _image_url_from_response(response: dict[str, Any]) -> str | None:
    if isinstance(response.get("url"), str):
        return response["url"]
    data = response.get("data")
    if isinstance(data, list) and data:
        first_item = data[0]
        if isinstance(first_item, dict) and isinstance(first_item.get("url"), str):
            return first_item["url"]
    if isinstance(data, dict) and isinstance(data.get("url"), str):
        return data["url"]
    return None


def _image_base64_from_response(response: dict[str, Any]) -> str | None:
    if isinstance(response.get("b64_json"), str):
        return response["b64_json"]
    if isinstance(response.get("base64"), str):
        return response["base64"]

    data = response.get("data")
    if isinstance(data, list) and data:
        first_item = data[0]
        if isinstance(first_item, dict):
            if isinstance(first_item.get("b64_json"), str):
                return first_item["b64_json"]
            if isinstance(first_item.get("base64"), str):
                return first_item["base64"]
    if isinstance(data, dict):
        if isinstance(data.get("b64_json"), str):
            return data["b64_json"]
        if isinstance(data.get("base64"), str):
            return data["base64"]
    return None
