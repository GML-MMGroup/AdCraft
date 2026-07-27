"""Private Pi Agent runtime routes with no public API compatibility contract."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.agent_runtime import (
    AgentStructuredSubmission,
    AgentToolCall,
    AgentToolResult,
    SpecialistDraft,
)
from app.services.v2_agent_credential_broker import (
    AgentCredentialError,
    V2AgentCredentialBroker,
)


router = APIRouter(prefix="/internal/v1")


def require_agent_internal_auth(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.agent_runtime_internal_token
    supplied = authorization.removeprefix("Bearer ") if authorization else None
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "agent_internal_auth_failed",
                "message": "Agent runtime authentication failed.",
            },
        )


@router.get(
    "/agent-runtime-config/{credential_ref}",
    dependencies=[Depends(require_agent_internal_auth)],
)
def get_agent_runtime_config(
    credential_ref: str,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    try:
        snapshot = V2AgentCredentialBroker(settings).snapshot(credential_ref)
    except AgentCredentialError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": error.code, "message": error.message},
        ) from error
    return {
        "protocol_version": snapshot.protocol_version,
        "provider": snapshot.provider,
        "model_id": snapshot.model_id,
        "base_url": snapshot.base_url,
        "api_key": snapshot.api_key,
    }


@router.post(
    "/agent-tools/execute",
    response_model=AgentToolResult,
    dependencies=[Depends(require_agent_internal_auth)],
)
def execute_agent_tool(call: AgentToolCall) -> AgentToolResult:
    if call.tool_name != "submit_structured_result":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "agent_tool_not_allowed",
                "message": "Agent tool is not available for this operation.",
            },
        )
    try:
        submission = AgentStructuredSubmission.model_validate(call.arguments)
        if submission.contract_name != "SpecialistDraft":
            raise ValueError("Unsupported structured contract")
        SpecialistDraft.model_validate(submission.value)
    except (ValidationError, ValueError):
        return AgentToolResult(
            run_id=call.run_id,
            tool_call_id=call.tool_call_id,
            status="rejected",
            result={
                "accepted": False,
                "violations": ["Structured submission does not match the requested contract."],
                "repair_allowed": submission.attempt < 2 if "submission" in locals() else True,
            },
            error_code="agent_structured_output_invalid",
            error_message="Structured Agent output is invalid.",
        )
    return AgentToolResult(
        run_id=call.run_id,
        tool_call_id=call.tool_call_id,
        status="completed",
        result={
            "accepted": True,
            "normalized_result_id": submission.submission_id,
            "repair_allowed": False,
        },
    )
