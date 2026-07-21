from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2_prompt_eval import (
    V2PromptEvalComparisonReport,
    V2PromptEvalComparisonRequest,
    V2PromptEvalReplayRequest,
    V2PromptEvalReport,
    V2PromptEvalRunRequest,
)
from app.services.v2_prompt_eval_runner import V2PromptEvalError, V2PromptEvalRunner


router = APIRouter(prefix="/prompt-evals", tags=["v2-prompt-evals"])
workflow_router = APIRouter(prefix="/workflows", tags=["v2-prompt-evals"])


def get_v2_prompt_eval_runner(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2PromptEvalRunner:
    return V2PromptEvalRunner(settings)


@router.post("/run", response_model=V2PromptEvalReport)
def run_prompt_eval(
    request: V2PromptEvalRunRequest,
    runner: Annotated[V2PromptEvalRunner, Depends(get_v2_prompt_eval_runner)],
) -> V2PromptEvalReport:
    try:
        return runner.run_fixture(
            request.fixture_id,
            prompt_profile_id=request.prompt_profile_id,
            mode=request.mode,
            selected_stages=request.selected_stages,
        )
    except V2PromptEvalError as exc:
        raise _prompt_eval_http_error(exc) from exc


@router.get("/{eval_run_id}", response_model=V2PromptEvalReport)
def get_prompt_eval_report(
    eval_run_id: str,
    runner: Annotated[V2PromptEvalRunner, Depends(get_v2_prompt_eval_runner)],
) -> V2PromptEvalReport:
    try:
        return runner.load_report(eval_run_id)
    except V2PromptEvalError as exc:
        raise _prompt_eval_http_error(exc) from exc


@router.post("/compare", response_model=V2PromptEvalComparisonReport)
def compare_prompt_eval_profiles(
    request: V2PromptEvalComparisonRequest,
    runner: Annotated[V2PromptEvalRunner, Depends(get_v2_prompt_eval_runner)],
) -> V2PromptEvalComparisonReport:
    try:
        return runner.compare_profiles(request)
    except V2PromptEvalError as exc:
        raise _prompt_eval_http_error(exc) from exc


@workflow_router.post("/{workflow_id}/prompt-replay", response_model=V2PromptEvalReport)
def replay_workflow_prompts(
    workflow_id: str,
    request: V2PromptEvalReplayRequest,
    runner: Annotated[V2PromptEvalRunner, Depends(get_v2_prompt_eval_runner)],
) -> V2PromptEvalReport:
    try:
        return runner.replay_workflow(
            workflow_id,
            prompt_profile_id=request.prompt_profile_id,
            mode=request.mode,
            selected_stages=request.selected_stages,
        )
    except V2PromptEvalError as exc:
        raise _prompt_eval_http_error(exc) from exc


def _prompt_eval_http_error(exc: V2PromptEvalError) -> HTTPException:
    if exc.code in {"prompt_eval_fixture_not_found", "prompt_eval_report_not_found"}:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        )
    if exc.code in {
        "prompt_eval_profile_not_found",
        "prompt_eval_schema_failed",
        "prompt_eval_quality_failed",
        "prompt_eval_replay_not_supported",
        "prompt_eval_ab_regression_failed",
    }:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        )
    if exc.code in {"prompt_eval_external_provider_blocked", "prompt_eval_stage_failed"}:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": str(exc)},
        )
    if exc.code == "prompt_eval_report_write_failed":
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": exc.code, "message": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": exc.code, "message": str(exc)},
    )
