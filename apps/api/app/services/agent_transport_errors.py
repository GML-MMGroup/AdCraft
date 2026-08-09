"""Narrow transport failure classification for Agent model calls."""

from __future__ import annotations

from app.schemas.agent_operation_recovery import AgentTransportClassificationV2


_RETRYABLE_CODES = {
    "ECONNRESET",
    "ECONNREFUSED",
    "ETIMEDOUT",
    "EAI_AGAIN",
    "ENOTFOUND",
    "ERR_SSL_UNEXPECTED_EOF_WHILE_READING",
}
_RETRYABLE_STATUSES = {502, 503, 504}
_RETRYABLE_MESSAGE_PARTS = (
    "connection reset",
    "remote disconnect",
    "socket hang up",
    "tls eof",
    "unexpected eof",
    "dns lookup",
    "connect failed",
)


def classify_agent_transport_error(
    *,
    code: str | None,
    status_code: int | None,
    message: str,
    retry_after_seconds: float | None = None,
) -> AgentTransportClassificationV2:
    normalized_code = str(code or "").upper()
    normalized_message = message.casefold()
    retryable = (
        normalized_code in _RETRYABLE_CODES
        or status_code in _RETRYABLE_STATUSES
        or any(part in normalized_message for part in _RETRYABLE_MESSAGE_PARTS)
        or (status_code == 429 and retry_after_seconds is not None)
    )
    return AgentTransportClassificationV2(
        code="agent_transport_failed",
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )
