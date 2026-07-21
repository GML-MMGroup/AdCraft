"""Validation and canonical serialization for V2 runtime event payloads."""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.persistence.errors import V2PersistenceError


MAX_PAYLOAD_BYTES = 65_536
_BARE_BASE64_MINIMUM_LENGTH = 1_024
_BARE_BASE64_PREFIX_LENGTH = 4_096
_WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def serialize_event_payload(payload: dict[str, Any]) -> str:
    """Validate and serialize a complete payload before opening a database transaction."""

    _validate_value(payload, path="$")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise _payload_error(
            "v2_event_payload_too_large",
            "V2 event payload exceeds the maximum allowed size.",
        )
    return serialized


def _validate_value(value: Any, *, path: str) -> None:
    if isinstance(value, str):
        _validate_string(value)
        return

    if isinstance(value, Mapping):
        for key, child in value.items():
            _validate_value(child, path=f"{path}.{key}")
        return

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_value(child, path=f"{path}[{index}]")


def _validate_string(value: str) -> None:
    lower_value = value.lower()
    if lower_value.startswith(("data:image/", "data:video/", "data:audio/")):
        raise _payload_error(
            "v2_event_payload_embedded_media",
            "V2 event payload contains embedded media.",
        )

    if _is_absolute_filesystem_path(value):
        raise _payload_error(
            "v2_event_payload_absolute_path",
            "V2 event payload contains an absolute filesystem path.",
        )

    if _is_recognized_bare_base64_media(value):
        raise _payload_error(
            "v2_event_payload_embedded_media",
            "V2 event payload contains embedded media.",
        )


def _is_absolute_filesystem_path(value: str) -> bool:
    if value.startswith(("/media/", "/api/")):
        return False
    return (
        value.startswith("/")
        or value.startswith("\\\\")
        or bool(_WINDOWS_DRIVE_PATH_PATTERN.match(value))
    )


def _is_recognized_bare_base64_media(value: str) -> bool:
    if len(value) < _BARE_BASE64_MINIMUM_LENGTH:
        return False

    encoded_prefix = value[:_BARE_BASE64_PREFIX_LENGTH]
    encoded_prefix = encoded_prefix[: len(encoded_prefix) - (len(encoded_prefix) % 4)]
    if not encoded_prefix:
        return False

    try:
        decoded_prefix = base64.b64decode(encoded_prefix, validate=True)
    except (binascii.Error, ValueError):
        return False
    return _has_media_magic(decoded_prefix)


def _has_media_magic(value: bytes) -> bool:
    return (
        value.startswith(b"\x89PNG\r\n\x1a\n")
        or value.startswith(b"\xff\xd8\xff")
        or value.startswith((b"GIF87a", b"GIF89a"))
        or value.startswith(b"ID3")
        or value.startswith(b"OggS")
        or (value.startswith(b"RIFF") and value[8:12] in {b"WEBP", b"WAVE"})
        or len(value) >= 8
        and value[4:8] == b"ftyp"
    )


def _payload_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="payload")
