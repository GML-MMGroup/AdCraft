from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json

import pytest
from sqlalchemy import insert

from app.persistence.agent_run_repository import AgentRunRepository
from app.persistence.database import create_v2_database
from app.persistence.models import (
    AgentCanvasChatTurnRow,
    AgentCanvasConversationRow,
    AgentCanvasWorkflowRow,
    ProjectRow,
)
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_runtime import (
    AgentRunContext,
    AgentRunRequest,
    AgentStructuredFallbackAuditV1,
    AgentStructuredSubmission,
)
from app.services.v2_agent_structured_validation import (
    V2AgentStructuredValidationService,
)


@pytest.fixture
def persisted_run(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "v2").mkdir(parents=True)
    database = create_v2_database(data_dir)
    upgrade_v2_schema(database)
    workflow_id = "workflow-1"
    conversation_id = "conversation-1"
    turn_id = "turn-1"
    timestamp = datetime.now(timezone.utc)
    timestamp_text = timestamp.isoformat()
    with database.engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                project_id="project-1",
                name="Test",
                description="",
                status="active",
                is_favorite=False,
                cover_asset_id=None,
                project_version=1,
                created_at=timestamp_text,
                updated_at=timestamp_text,
                deleted_at=None,
            )
        )
        connection.execute(
            insert(AgentCanvasWorkflowRow).values(
                workflow_id=workflow_id,
                project_id="project-1",
                workflow_schema_version=2,
                canvas_model="agent_canvas_v1",
                revision=1,
                layout_revision=1,
                created_at=timestamp_text,
                updated_at=timestamp_text,
            )
        )
        connection.execute(
            insert(AgentCanvasConversationRow).values(
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                created_at=timestamp_text,
                updated_at=timestamp_text,
            )
        )
        connection.execute(
            insert(AgentCanvasChatTurnRow).values(
                turn_id=turn_id,
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                turn_kind="user_message",
                status="completed",
                request_json=json.dumps({"text": "请制作60秒竖版广告"}, ensure_ascii=False),
                creation_mode_json=None,
                guidance_session_revision=None,
                idempotency_key="turn-key-1",
                retry_of_turn_id=None,
                retry_attempt_no=1,
                retryable=False,
                operation_stage=None,
                operation_failure_json=None,
                retry_snapshot_json="{}",
                error_code=None,
                error_message=None,
                created_at=timestamp_text,
                updated_at=timestamp_text,
            )
        )
    request = AgentRunRequest(
        run_id="run-1",
        request_id="request-1",
        contract_digest="0" * 64,
        context_snapshot_id="snapshot-1",
        agent_name="video_agent",
        operation="decide_turn_intent",
        deadline_at=timestamp + timedelta(minutes=5),
        model_policy_id="test-policy",
        context=AgentRunContext(
            operation="decide_turn_intent",
            user_input="请制作60秒竖版广告",
            conversation_id=conversation_id,
            workflow_id=workflow_id,
        ),
        contract_name="CompactTurnIntentDecisionV3",
        validation_profile="agent_intake_source_quotes_v1",
        validation_context={"source_turn_id": turn_id},
    )
    repository = AgentRunRepository(database)
    run, created = repository.create_or_load(
        request,
        lease_owner_id="test-owner",
        lease_duration_seconds=120,
        now=timestamp,
    )
    assert created
    try:
        yield repository, run
    finally:
        database.dispose()


def submission(run, value, *, run_id=None, attempt=1):
    return AgentStructuredSubmission(
        run_id=run.run_id if run_id is None else run_id,
        submission_id="submission-1",
        contract_name=run.contract_name,
        value=value,
        attempt=attempt,
    )


def submission_with_contract(run, value, *, contract_name, attempt=2):
    return AgentStructuredSubmission(
        run_id=run.run_id,
        submission_id="submission-1",
        contract_name=contract_name,
        value=value,
        attempt=attempt,
    )


def duration_candidate(*, source_quote="60秒", value="60"):
    return {
        "mode": "guided_production",
        "objective": "制作60秒竖版广告",
        "requirement_patch": {
            "controls_to_set": {
                "target_duration_sec": {"value": value, "source_quote": source_quote}
            }
        },
    }


def test_accepts_normalized_duration_and_checks_quote_on_retained_value(persisted_run):
    repository, run = persisted_run
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, duration_candidate()),
    )

    assert result.accepted is True
    assert result.normalized_value["requirement_patch"]["controls_to_set"]["duration_seconds"]["value"] == 60.0
    assert result.normalized_value["requirement_patch"]["controls_to_set"]["duration_seconds"]["source_quote"] == "60秒"


def test_accepts_provider_duration_seconds_alias_and_checks_source_quote(persisted_run):
    repository, run = persisted_run
    value = {
        "mode": "guided_production",
        "objective": "制作60秒竖版广告",
        "requirement_patch": {
            "controls_to_set": {
                "target_duration_seconds": {"value": "60", "source_quote": "60秒"}
            }
        },
    }
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, value),
    )

    assert result.accepted is True
    control = result.normalized_value["requirement_patch"]["controls_to_set"]["duration_seconds"]
    assert control["value"] == 60.0
    assert control["source_quote"] == "60秒"


def test_alias_quote_is_checked_after_normalized_contract_validation(persisted_run):
    repository, run = persisted_run
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, duration_candidate(source_quote="120秒")),
    )

    assert result.accepted is False
    assert [item.code for item in result.violations] == ["requirement_source_quote_invalid"]
    assert result.violations[0].field_path == (
        "requirement_patch.controls_to_set.duration_seconds.source_quote"
    )


def test_unknown_presence_defaults_to_unspecified_without_unintended_action(persisted_run):
    repository, run = persisted_run
    value = {
        "mode": "guided_production",
        "objective": "制作广告",
        "explicit_elements": {
            "product": {"presence": "mystery", "source_quote": "广告"}
        },
    }
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, value),
    )

    assert result.accepted is True
    assert result.violations == ()
    assert result.normalized_value["explicit_elements"]["product"]["presence"] == "unspecified"
    assert "requirement_patch" not in result.normalized_value


def test_unknown_top_level_field_remains_forbidden(persisted_run):
    repository, run = persisted_run
    value = {**duration_candidate(), "unexpected": True}
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, value),
    )

    assert result.accepted is False
    assert any(item.code == "extra_forbidden" for item in result.violations)
    assert all(item.code != "requirement_source_quote_invalid" for item in result.violations)


def test_identity_mismatch_is_first_gate(persisted_run):
    repository, run = persisted_run
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, duration_candidate(), run_id="other-run"),
    )

    assert result.accepted is False
    assert [item.code for item in result.violations] == ["agent_run_mismatch"]


def test_alias_conflict_rejects_only_normalization_violation(persisted_run):
    repository, run = persisted_run
    value = {
        **duration_candidate(source_quote="不存在的引文"),
        "requirement_patch": {
            "controls_to_set": {
                "target_duration_sec": {"value": "60", "source_quote": "不存在的引文"},
                "duration_seconds": {"value": 61.0, "source_quote": "另一个不存在的引文"},
            }
        },
    }
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, value),
    )

    assert result.accepted is False
    assert [item.code for item in result.violations] == [
        "agent_structured_normalization_alias_conflict"
    ]


def test_second_submission_invalid_source_quote_returns_safe_fallback(persisted_run):
    repository, run = persisted_run
    value = {
        **duration_candidate(source_quote="不存在的引文"),
        "assistant_message": "我已理解你的广告需求。",
    }
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, value, attempt=2),
    )

    assert result.accepted is True
    assert result.normalized_result_id == "submission-1"
    assert result.repair_allowed is False
    assert result.normalized_value == {
        "mode": "ordinary_conversation",
        "objective": "Preserve a safe conversational response after structured validation failed.",
        "assistant_message": "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。",
    }
    assert result.fallback_audit is not None
    assert result.fallback_audit.error_code == "agent_structured_fallback_applied"
    assert result.fallback_audit.failure_codes == ("requirement_source_quote_invalid",)
    assert result.fallback_audit.validation_paths == (
        "requirement_patch.controls_to_set.duration_seconds.source_quote",
    )
    assert result.fallback_audit.submission_attempt == 2
    assert result.fallback_audit.used_model_message is False
    assert result.fallback_audit.reason == "validation_exhausted"
    assert result.normalization_audit is not None
    assert result.normalization_audit.rule_ids
    assert result.normalization_audit.normalized_path_count >= 1
    assert "requested_capability" not in result.normalized_value
    assert "explicit_elements" not in result.normalized_value
    assert "requirement_patch" not in result.normalized_value


@pytest.mark.parametrize(
    ("assistant_message", "expected_used_model_message"),
    [
        ("   \n\t", False),
        ("\u0000\u0001", False),
        (123, False),
        ("x" * 2_001, False),
    ],
)
def test_second_submission_invalid_assistant_message_uses_deterministic_fallback(
    persisted_run,
    assistant_message,
    expected_used_model_message,
):
    repository, run = persisted_run
    value = {
        **duration_candidate(source_quote="不存在的引文"),
        "assistant_message": assistant_message,
    }
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, value, attempt=2),
    )

    assert result.accepted is True
    assert result.normalized_value["assistant_message"] == (
        "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。"
    )
    assert result.fallback_audit.used_model_message is expected_used_model_message


def test_first_submission_with_invalid_source_quote_remains_rejected(persisted_run):
    repository, run = persisted_run
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(
            run,
            {**duration_candidate(source_quote="不存在的引文"), "assistant_message": "请稍后再试。"},
            attempt=1,
        ),
    )

    assert result.accepted is False
    assert [item.code for item in result.violations] == ["requirement_source_quote_invalid"]


def test_second_submission_different_contract_remains_rejected(persisted_run):
    repository, run = persisted_run
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission_with_contract(
            run,
            {"mode": "ordinary_conversation", "objective": "hello"},
            contract_name="TurnIntentDecisionV2",
        ),
    )

    assert result.accepted is False
    assert [item.code for item in result.violations] == ["agent_contract_mismatch"]


def test_second_submission_persisted_noncompact_contract_remains_rejected(persisted_run):
    repository, run = persisted_run
    run = replace(run, contract_name="TurnIntentDecisionV2")
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(run, {"unexpected": True}, attempt=2),
    )

    assert result.accepted is False
    assert result.fallback_audit is None
    assert result.violations


def test_second_submission_invalid_validation_context_remains_rejected(persisted_run):
    repository, run = persisted_run
    run.validation_context["source_turn_id"] = "missing-turn"
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(
            run,
            {**duration_candidate(source_quote="不存在的引文"), "assistant_message": "请重试。"},
            attempt=2,
        ),
    )

    assert result.accepted is False
    assert [item.code for item in result.violations] == ["agent_validation_context_invalid"]


def test_second_submission_invalid_context_blocks_fallback_before_schema_errors(persisted_run):
    repository, run = persisted_run
    run.validation_context.pop("source_turn_id")
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(
            run,
            {
                **duration_candidate(source_quote="不存在的引文"),
                "assistant_message": "请重试。",
                "unexpected": True,
            },
            attempt=2,
        ),
    )

    assert result.accepted is False
    assert result.fallback_audit is None
    assert [item.code for item in result.violations] == ["agent_validation_context_invalid"]


def test_fallback_model_message_is_trimmed_after_control_cleanup(persisted_run):
    repository, run = persisted_run
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(
            run,
            {
                **duration_candidate(source_quote="不存在的引文"),
                "assistant_message": "  hi  ",
            },
            attempt=2,
        ),
    )

    assert result.accepted is True
    assert result.normalized_value["assistant_message"] == (
        "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。"
    )
    assert result.fallback_audit is not None
    assert result.fallback_audit.used_model_message is False


def test_fallback_model_message_preserves_inner_newline_and_tab(persisted_run):
    repository, run = persisted_run
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(
            run,
            {
                **duration_candidate(source_quote="不存在的引文"),
                "assistant_message": "  hi\n\tthere\u0000  ",
            },
            attempt=2,
        ),
    )

    assert result.accepted is True
    assert result.normalized_value["assistant_message"] == (
        "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。"
    )


def test_fallback_replaces_misleading_model_message(persisted_run):
    repository, run = persisted_run
    result = V2AgentStructuredValidationService(repository).validate(
        run=run,
        submission=submission(
            run,
            {
                **duration_candidate(source_quote="不存在的引文"),
                "assistant_message": "我已开启创作计划",
            },
            attempt=2,
        ),
    )

    assert result.accepted is True
    assert result.normalized_value["assistant_message"] == (
        "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。"
    )
    assert result.fallback_audit is not None
    assert result.fallback_audit.used_model_message is False


def test_repair_json_invalid_fallback_audit_allows_empty_failure_codes():
    audit = AgentStructuredFallbackAuditV1(
        contract_name="CompactTurnIntentDecisionV3",
        error_code="agent_structured_fallback_applied",
        failure_codes=(),
        validation_paths=(),
        submission_attempt=2,
        used_model_message=False,
        reason="repair_json_invalid",
    )

    assert audit.failure_codes == ()
