import json
import re
from collections.abc import Mapping
from typing import Any

DEFAULT_LLM_TEXT_CONTEXT_MAX_CHARS = 60_000

_DATA_URL_PATTERN = re.compile(
    r"data:(?P<mime>(?:image|video|audio)/[A-Za-z0-9.+-]+);base64,"
    r"(?P<payload>[A-Za-z0-9+/=\r\n]+)"
)
_RAW_MEDIA_FIELD_KEYS = {
    "base64",
    "b64",
    "b64_json",
    "data_url",
    "image_base64",
    "video_base64",
    "audio_base64",
    "raw_base64",
    "raw_bytes",
    "file_bytes",
    "content_bytes",
    "binary_payload",
    "encoded_data",
    "content_base64",
    "payload_base64",
}
_SENSITIVE_FIELD_KEYS = {
    "api_key",
    "api_token",
    "access_key",
    "access_token",
    "authorization",
    "bearer_token",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "secret_key",
    "session_token",
    "token",
}
_IDENTITY_STRING_KEYS = {
    "asset_id",
    "entity_id",
    "library_entity_id",
    "library_asset_id",
    "node_id",
    "node_type",
    "item_id",
    "slot_id",
    "semantic_type",
    "media_type",
    "mime_type",
    "display_name",
    "filename",
    "public_url",
    "local_path",
    "source",
    "source_type",
    "role",
    "reference_mode",
    "metadata_path",
    "remote_url",
    "url",
}
_TRIM_STEPS = (1200, 600, 300, 120)


def sanitize_context_for_llm_text(value: Any) -> Any:
    """Return a copy safe to serialize into text-only LLM prompts."""

    return _sanitize_value(value, key=None, siblings=None)


def sanitize_context_for_llm_text_with_warnings(
    value: Any,
    *,
    max_chars: int = DEFAULT_LLM_TEXT_CONTEXT_MAX_CHARS,
) -> tuple[Any, list[dict[str, Any]]]:
    sanitized = sanitize_context_for_llm_text(value)
    initial_chars = _serialized_len(sanitized)
    if initial_chars <= max_chars:
        return sanitized, []

    trimmed = sanitized
    for max_string_chars in _TRIM_STEPS:
        trimmed = _trim_long_strings(trimmed, max_string_chars=max_string_chars)
        if _serialized_len(trimmed) <= max_chars:
            break

    final_chars = _serialized_len(trimmed)
    return trimmed, [
        {
            "code": "llm_context_trimmed",
            "message": "LLM text context was trimmed after media payload sanitization.",
            "original_chars": initial_chars,
            "sanitized_chars": final_chars,
            "max_chars": max_chars,
        }
    ]


def _sanitize_value(value: Any, *, key: str | None, siblings: Mapping[str, Any] | None) -> Any:
    normalized_key = key.lower() if isinstance(key, str) else ""
    if isinstance(value, Mapping):
        return {
            item_key: _sanitize_value(
                item_value,
                key=str(item_key),
                siblings=value,
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, key=key, siblings=siblings) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, key=key, siblings=siblings) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _omitted_binary_placeholder(value)
    if isinstance(value, str):
        return _sanitize_string(value, key=normalized_key, siblings=siblings)
    return value


def _sanitize_string(
    value: str,
    *,
    key: str,
    siblings: Mapping[str, Any] | None,
) -> str:
    stripped = value.strip()
    if _is_sensitive_field(key):
        return f"[omitted_secret field={key}]"
    if _is_data_url(stripped):
        return _omitted_data_url_placeholder(stripped, siblings=siblings)
    if key == "model_input_value":
        return value
    if _is_raw_media_field(key):
        return _omitted_payload_placeholder(value, key=key, siblings=siblings)
    if "data:" in value and ";base64," in value:
        return _DATA_URL_PATTERN.sub(
            lambda match: _omitted_data_url_placeholder(
                match.group(0),
                siblings=siblings,
                mime_type=match.group("mime"),
            ),
            value,
        )
    return value


def _is_raw_media_field(key: str) -> bool:
    return key in _RAW_MEDIA_FIELD_KEYS or key.endswith("_base64") or key.endswith("_bytes")


def _is_sensitive_field(key: str) -> bool:
    return (
        key in _SENSITIVE_FIELD_KEYS
        or key.endswith("_api_key")
        or key.endswith("_access_token")
        or key.endswith("_secret")
        or key.endswith("_token")
        or key.endswith("_password")
    )


def _is_data_url(value: str) -> bool:
    return bool(_DATA_URL_PATTERN.match(value))


def _omitted_data_url_placeholder(
    value: str,
    *,
    siblings: Mapping[str, Any] | None,
    mime_type: str | None = None,
) -> str:
    media_type = _media_type(
        siblings=siblings, mime_type=mime_type or _mime_type_from_data_url(value)
    )
    return (
        f"[omitted_data_url media_type={media_type or 'unknown'} "
        f"size_bytes={_size_bytes(siblings=siblings, value=value)}]"
    )


def _omitted_payload_placeholder(
    value: str,
    *,
    key: str,
    siblings: Mapping[str, Any] | None,
) -> str:
    media_type = _media_type(siblings=siblings, mime_type=None)
    return (
        f"[omitted_media_payload field={key} media_type={media_type or 'unknown'} "
        f"size_bytes={_size_bytes(siblings=siblings, value=value)}]"
    )


def _omitted_binary_placeholder(value: bytes | bytearray | memoryview) -> str:
    return f"[omitted_binary size_bytes={len(value)}]"


def _mime_type_from_data_url(value: str) -> str | None:
    match = _DATA_URL_PATTERN.match(value)
    return match.group("mime") if match else None


def _media_type(
    *,
    siblings: Mapping[str, Any] | None,
    mime_type: str | None,
) -> str | None:
    if mime_type:
        return mime_type.split("/", 1)[0]
    if not siblings:
        return None
    for key in ("media_type", "asset_type", "type", "kind"):
        value = siblings.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = siblings.get("mime_type")
    if isinstance(value, str) and "/" in value:
        return value.split("/", 1)[0]
    return None


def _size_bytes(*, siblings: Mapping[str, Any] | None, value: str) -> int:
    if siblings:
        direct = siblings.get("size_bytes")
        if isinstance(direct, int) and direct >= 0:
            return direct
        metadata = siblings.get("metadata")
        if isinstance(metadata, Mapping):
            nested = metadata.get("size_bytes")
            if isinstance(nested, int) and nested >= 0:
                return nested
    return len(value.encode("utf-8"))


def _trim_long_strings(value: Any, *, max_string_chars: int, key: str | None = None) -> Any:
    if isinstance(value, Mapping):
        return {
            item_key: _trim_long_strings(
                item_value,
                max_string_chars=max_string_chars,
                key=str(item_key),
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [
            _trim_long_strings(item, max_string_chars=max_string_chars, key=key) for item in value
        ]
    if isinstance(value, str) and len(value) > max_string_chars and not _preserve_string_key(key):
        return f"{value[:max_string_chars]}... [truncated chars={len(value)}]"
    return value


def _preserve_string_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.lower()
    return (
        normalized in _IDENTITY_STRING_KEYS
        or normalized == "id"
        or normalized.endswith("_id")
        or normalized.endswith("_ids")
        or normalized.endswith("_url")
        or normalized.endswith("_path")
    )


def _serialized_len(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))
