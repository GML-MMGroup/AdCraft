"""Canonical private operation vocabulary for durable Agent continuations."""

from __future__ import annotations

from typing import Literal


ContinuationOperationV2 = Literal[
    "next_action",
    "capability_command",
    "capability_materialization",
]
RetryableContinuationOperationV1 = Literal[
    "next_action",
    "capability_command",
]

CONTINUATION_OPERATIONS_V2: frozenset[str] = frozenset(
    {
        "next_action",
        "capability_command",
        "capability_materialization",
    }
)
RETRYABLE_CONTINUATION_OPERATIONS_V1: frozenset[str] = frozenset(
    {
        "next_action",
        "capability_command",
    }
)
