"""Closed manual retry policy for typed Agent Canvas operations."""

from __future__ import annotations


_EXPLICIT_RETRYABLE_ERRORS = frozenset(
    {
        "agent_provider_timeout",
        "agent_provider_transport_failed",
        "agent_structured_output_invalid",
    }
)


def explicit_turn_retryable(error_code: str) -> bool:
    """Return whether a terminal typed operation may receive one fresh attempt."""

    return error_code in _EXPLICIT_RETRYABLE_ERRORS
