"""Durable intent boundary for paid Agent Canvas provider submission."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_runtime import ResolvedModelExecutionV1, ResolvedModelExecutionV2
from app.schemas.agent_canvas_runtime_authority import ProviderSubmissionIntentV2


class ProviderSubmissionIntentService:
    """Prepare and advance one immutable logical provider operation."""

    def __init__(self, runtime: AgentCanvasRuntimeRepository) -> None:
        self._runtime = runtime

    def prepare(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        model_resolution: ResolvedModelExecutionV1,
        request_payload: object,
        now: datetime,
    ) -> ProviderSubmissionIntentV2:
        member = next(
            (
                candidate
                for candidate in self._runtime.list_members(execution_id)
                if candidate.node_id == node_id
            ),
            None,
        )
        if member is None:
            raise V2PersistenceError(
                "execution_member_not_found",
                "Execution member was not found.",
                stage="agent_canvas_provider_submission",
            )
        request_digest = _digest(request_payload)
        logical_key = f"{execution_id}:{member.member_id}:{member.attempt_no + 1}"
        capabilities = model_resolution.capability_metadata
        supports_token = bool(capabilities.get("supports_provider_idempotency_token"))
        supports_lookup = bool(capabilities.get("supports_remote_task_lookup"))
        token = (
            "provider_" + hashlib.sha256(logical_key.encode("utf-8")).hexdigest()[:32]
            if supports_token
            else None
        )
        intent_id = "intent_" + hashlib.sha256(logical_key.encode("utf-8")).hexdigest()[:32]
        return self._runtime.put_submission_intent(
            ProviderSubmissionIntentV2(
                intent_id=intent_id,
                logical_operation_key=logical_key,
                request_digest=request_digest,
                workflow_id=workflow_id,
                execution_id=execution_id,
                member_id=member.member_id,
                node_id=node_id,
                provider=model_resolution.provider_id,
                model_id=model_resolution.provider_model_id,
                attempt_no=member.attempt_no + 1,
                supports_idempotency_token=supports_token,
                supports_remote_task_lookup=supports_lookup,
                frozen_model_resolution=(
                    model_resolution
                    if isinstance(model_resolution, ResolvedModelExecutionV2)
                    else None
                ),
                provider_idempotency_token=token,
                state="prepared",
                created_at=now,
                updated_at=now,
            )
        )

    def confirm_remote_task(
        self,
        intent: ProviderSubmissionIntentV2,
        *,
        provider_task_id: str | None,
        remote_task_id: str | None,
        now: datetime,
    ) -> ProviderSubmissionIntentV2:
        confirmed = intent.model_copy(
            update={
                "provider_task_id": provider_task_id,
                "remote_task_id": remote_task_id,
                "state": "submitted",
                "updated_at": now,
            }
        )
        return self._runtime.update_submission_intent(
            confirmed,
            expected_state="prepared",
        )

    def mark_outcome_unknown(
        self,
        intent: ProviderSubmissionIntentV2,
        *,
        now: datetime,
    ) -> ProviderSubmissionIntentV2:
        if intent.supports_idempotency_token or intent.supports_remote_task_lookup:
            return intent
        unknown = intent.model_copy(update={"state": "outcome_unknown", "updated_at": now})
        return self._runtime.update_submission_intent(unknown, expected_state="prepared")

    def complete(
        self,
        intent: ProviderSubmissionIntentV2,
        *,
        now: datetime,
    ) -> ProviderSubmissionIntentV2:
        if intent.state == "completed":
            return intent
        completed = intent.model_copy(update={"state": "completed", "updated_at": now})
        return self._runtime.update_submission_intent(
            completed,
            expected_state=intent.state,
        )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
