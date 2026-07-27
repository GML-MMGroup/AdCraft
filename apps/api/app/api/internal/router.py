"""Private Pi Agent runtime routes with no public API compatibility contract."""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.persistence.agent_run_repository import AgentRunRepository
from app.persistence.agent_run_repository import AgentRunRepositoryError
from app.persistence.database import create_v2_database
from app.schemas.agent_runtime import (
    AgentStructuredSubmission,
    AgentToolCall,
    AgentToolResult,
)
from app.services.v2_agent_credential_broker import (
    AgentCredentialError,
    V2AgentCredentialBroker,
)
from app.services.v2_agent_structured_validation import (
    V2AgentStructuredValidationService,
)
from app.services.v2_agent_tool_gateway import (
    V2AgentToolGateway,
    WorkflowV2AgentToolDomain,
)


router = APIRouter(prefix="/internal/v1")
logger = logging.getLogger(__name__)


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
def execute_agent_tool(
    call: AgentToolCall,
    settings: Settings = Depends(get_settings),
) -> AgentToolResult:
    if call.tool_name != "submit_structured_result":
        database = create_v2_database(settings.media_data_dir)
        try:
            return V2AgentToolGateway(
                repository=AgentRunRepository(database),
                domain=WorkflowV2AgentToolDomain(settings),
            ).execute(call)
        finally:
            database.dispose()
    database = create_v2_database(settings.media_data_dir)
    repository = AgentRunRepository(database)
    try:
        submission = AgentStructuredSubmission.model_validate(call.arguments)
        run = repository.load(call.run_id)
        result = V2AgentStructuredValidationService(repository).validate(
            run=run,
            submission=submission,
        )
    except (ValidationError, AgentRunRepositoryError) as error:
        violations = [
            {
                "path": "run_id" if isinstance(error, AgentRunRepositoryError) else None,
                "code": (
                    error.code
                    if isinstance(error, AgentRunRepositoryError)
                    else "agent_submission_invalid"
                ),
                "message": (
                    error.message
                    if isinstance(error, AgentRunRepositoryError)
                    else "The structured Agent submission is invalid."
                ),
            }
        ]
        logger.warning(
            "agent_structured_submission_rejected contract=%s attempt=%s violations=%s",
            (submission.contract_name if "submission" in locals() else "unparseable_submission"),
            submission.attempt if "submission" in locals() else None,
            [{"path": item["path"], "code": item["code"]} for item in violations],
        )
        return AgentToolResult(
            run_id=call.run_id,
            tool_call_id=call.tool_call_id,
            status="rejected",
            result={
                "accepted": False,
                "violations": violations,
                "repair_allowed": submission.attempt < 2 if "submission" in locals() else True,
            },
            error_code="agent_structured_output_invalid",
            error_message="Structured Agent output is invalid.",
        )
    finally:
        database.dispose()

    serialized_violations = [
        {
            "path": violation.field_path,
            "code": violation.code,
            "message": violation.message,
            "expected": violation.expected,
            "actual": violation.actual,
        }
        for violation in result.violations
    ]
    if not result.accepted:
        logger.warning(
            "agent_structured_submission_rejected contract=%s attempt=%s violations=%s",
            submission.contract_name,
            submission.attempt,
            [
                {"path": item["path"], "code": item["code"]}
                for item in serialized_violations
            ],
        )
        return AgentToolResult(
            run_id=call.run_id,
            tool_call_id=call.tool_call_id,
            status="rejected",
            result={
                "accepted": False,
                "violations": serialized_violations,
                "repair_allowed": result.repair_allowed,
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
            "normalized_result_id": result.normalized_result_id,
            "value": result.normalized_value,
            "repair_allowed": False,
        },
    )
