"""Protected exact model input, never part of a committed response fixture."""

from __future__ import annotations

from hashlib import sha256
import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_MAX_BYTES = 1_048_576
_UNSAFE = re.compile(
    r"(?:https?://|file://|data:[\w/+.-]+[;,]|\bBearer\s+\S+|"
    r"\b(?:api[_-]?key|authorization|cookie|password|secret)\s*[:=]|"
    r"(?:^|[\s\"'])/(?:data|home|root|tmp|mnt|etc|var|Users)(?:/|\b)|"
    r"[A-Za-z]:[\\/]|\\\\[\w.-]+\\|\b(?:sk|sf)-[A-Za-z0-9_-]{16,})",
    re.IGNORECASE,
)
_FORBIDDEN_KEYS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "headers",
)
_PROVIDER_KEYS = frozenset(
    {
        "model",
        "messages",
        "max_tokens",
        "stream",
        "tools",
        "tool_choice",
        "response_format",
        "enable_thinking",
        "thinking_budget",
        "reasoning_effort",
        "provider",
        "temperature",
        "top_p",
        "stop",
        "max_completion_tokens",
    }
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _hash(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("acceptance_model_trace_unsafe")
        result[key] = value
    return result


def _safe(value: object, depth: int = 0) -> None:
    if depth > 40:
        raise ValueError("acceptance_model_trace_unsafe")
    if isinstance(value, str):
        if _UNSAFE.search(value):
            raise ValueError("acceptance_model_trace_unsafe")
    elif isinstance(value, dict):
        for key, item in value.items():
            if any(part in key.casefold() for part in _FORBIDDEN_KEYS):
                raise ValueError("acceptance_model_trace_unsafe")
            _safe(key, depth + 1)
            _safe(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _safe(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("acceptance_model_trace_unsafe")


def _parsed(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value, object_pairs_hook=_object)
        if not isinstance(parsed, dict) or _json(parsed) != value:
            raise ValueError("acceptance_model_trace_unsafe")
        _safe(parsed)
        return parsed
    except (ValueError, RecursionError) as error:
        raise ValueError("acceptance_model_trace_unsafe") from error


class AgentModelTraceRequestSnapshotV1(BaseModel):
    """Exact canonical request bytes from Pi, protected by Python storage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    contract_name: str = Field(min_length=1, max_length=160)
    system_prompt: str = Field(max_length=262_144)
    user_prompt: str = Field(max_length=262_144)
    output_schema_json: str = Field(min_length=2, max_length=262_144)
    provider_request_json: str = Field(min_length=2, max_length=524_288)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "AgentModelTraceRequestSnapshotV1":
        payload = self.model_dump(mode="json")
        if len(_json(payload).encode()) > _MAX_BYTES:
            raise ValueError("acceptance_model_trace_unsafe")
        _safe(payload)
        _parsed(self.output_schema_json)
        provider = _parsed(self.provider_request_json)
        if set(provider) - _PROVIDER_KEYS:
            raise ValueError("acceptance_model_trace_unsafe")
        return self

    @property
    def digest(self) -> str:
        return _hash(_json(dict(sorted(self.model_dump(mode="json").items()))))

    def validate_identity(self, identity: Any) -> None:
        """Compare every reconstructable digest without dropping any request field."""

        logical = {
            "contract_name": self.contract_name,
            "operation": identity.operation,
            "schema": _parsed(self.output_schema_json),
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
        }
        if (
            identity.request_digest != _hash(self.provider_request_json)
            or identity.schema_digest != _hash(self.output_schema_json)
            or identity.prompt_digest
            != _hash(
                _json(
                    {
                        "system_prompt": self.system_prompt,
                        "user_prompt": self.user_prompt,
                    }
                )
            )
            or identity.logical_invocation_key
            != identity.operation + ":" + _hash(_json(logical))[7:]
        ):
            raise ValueError("acceptance_model_replay_mismatch")
