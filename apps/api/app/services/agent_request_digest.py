"""Canonical digests for credential-free frozen Agent requests."""

from __future__ import annotations

from app.schemas.agent_runtime import AgentRunRequest, canonical_agent_run_request_digest


def frozen_agent_request_digest(request: AgentRunRequest) -> str:
    return canonical_agent_run_request_digest(request)
