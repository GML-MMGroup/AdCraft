"""Stable request identity for durable V2 Pi Agent actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel


_VOLATILE_KEYS = {
    "created_at",
    "deadline_at",
    "finished_at",
    "last_polled_at",
    "request_id",
    "run_id",
    "started_at",
    "timestamp",
    "updated_at",
}
_SENSITIVE_KEY_PARTS = ("api_key", "authorization", "credential", "secret", "token")


@dataclass(frozen=True, slots=True)
class AgentRequestIdentity:
    request_id: str
    run_id: str
    input_digest: str


def agent_request_identity(
    *,
    conversation_id: str | None,
    action_id: str,
    operation: str,
    target_revision: int | None,
    normalized_input: BaseModel | Mapping[str, Any],
) -> AgentRequestIdentity:
    """Return one safe deterministic identity for the same semantic Agent action."""

    raw_input = (
        normalized_input.model_dump(mode="json")
        if isinstance(normalized_input, BaseModel)
        else dict(normalized_input)
    )
    canonical = {
        "conversation_id": conversation_id,
        "action_id": action_id,
        "operation": operation,
        "target_revision": target_revision,
        "input": _canonical_value(raw_input),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = sha256(encoded).hexdigest()
    return AgentRequestIdentity(
        request_id=f"req_{digest[:32]}",
        run_id=f"arun_{digest[32:64]}",
        input_digest=f"sha256:{digest}",
    )


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        canonical: dict[str, Any] = {}
        for key, child in value.items():
            normalized_key = str(key)
            folded = normalized_key.casefold()
            if folded in _VOLATILE_KEYS or any(
                part in folded for part in _SENSITIVE_KEY_PARTS
            ):
                continue
            canonical[normalized_key] = _canonical_value(child)
        return canonical
    if isinstance(value, (list, tuple)):
        return [_canonical_value(child) for child in value]
    return value
