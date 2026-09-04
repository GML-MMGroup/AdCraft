"""Bounded local recovery for durable Agent Canvas result publication."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_result_publication_repository import (
    AgentCanvasResultPublicationIntentRepository,
)
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_runtime import NodeExecutionLeaseV2
from app.schemas.agent_canvas_runtime_authority import (
    CanvasExecutionResultCommitCommandV2,
    CanvasResultPublicationIntentV1,
    PreparedNodeResultV2,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_execution_result_commit import (
    AgentCanvasExecutionResultCommitService,
)


RecoveryDisposition = Literal["committed", "deferred", "abandoned"]


class AgentCanvasResultPublicationRecoveryService:
    """Recover verified local objects through the existing terminal authority."""

    def __init__(
        self,
        intents: AgentCanvasResultPublicationIntentRepository,
        assets: AgentCanvasAssetService,
        runtime: AgentCanvasRuntimeRepository,
        workflows: AgentCanvasWorkflowRepository,
        committer: AgentCanvasExecutionResultCommitService,
        *,
        owner_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if intents.database is not runtime.database or intents.database is not workflows.database:
            raise ValueError("Publication recovery authorities must share one database.")
        self._intents = intents
        self._assets = assets
        self._runtime = runtime
        self._workflows = workflows
        self._committer = committer
        self._owner_id = owner_id
        self._clock = clock

    def recover_execution(self, execution_id: str) -> tuple[RecoveryDisposition, ...]:
        now = self._clock()
        return tuple(
            self._recover(intent, now=now)
            for intent in self._intents.list_due(execution_id=execution_id, now=now)
        )

    def defer_member(
        self,
        *,
        execution_id: str,
        member_id: str,
        error_code: str,
    ) -> bool:
        """Schedule a durable handoff after its original worker cannot commit."""

        intent = self._intents.find_for_member(
            execution_id=execution_id,
            member_id=member_id,
        )
        if intent is None or intent.state not in {"preparing", "prepared"}:
            return False
        self._defer(intent, error_code, now=self._clock())
        return True

    def _recover(
        self,
        intent: CanvasResultPublicationIntentV1,
        *,
        now: datetime,
    ) -> RecoveryDisposition:
        lease = None
        member = next(
            (
                item
                for item in self._runtime.list_members(intent.execution_id)
                if item.member_id == intent.member_id and item.node_id == intent.node_id
            ),
            None,
        )
        if member is None:
            return self._close_without_publication(
                intent,
                "node_result_publication_source_invalid",
                now=now,
            )
        if member.state in {"succeeded", "failed", "cancelled"}:
            matching_receipt = next(
                (
                    receipt
                    for receipt in self._committer.list_receipts(intent.execution_id)
                    if receipt.logical_result_key == intent.logical_result_key
                    and receipt.payload_digest == intent.payload_digest
                    and receipt.outcome == "succeeded"
                ),
                None,
            )
            if matching_receipt is not None:
                self._intents.mark_committed(
                    intent.intent_id,
                    receipt_id=matching_receipt.commit_id,
                    now=now,
                )
                return "committed"
            return self._close_without_publication(
                intent,
                "node_result_publication_terminal_conflict",
                now=now,
            )
        execution = self._runtime.get_execution(intent.execution_id)
        if execution.cancel_requested or execution.status in {
            "completed",
            "partial_completed",
            "failed",
            "cancelled",
        }:
            return self._close_without_publication(
                intent,
                "node_result_publication_terminal_conflict",
                now=now,
            )
        if (
            member.run_intent_snapshot_id != intent.source_snapshot_id
            or member.run_intent_snapshot_digest != intent.source_snapshot_digest
        ):
            return self._abandon(intent, "node_result_publication_source_invalid", now=now)
        try:
            self._workflows.get_node(intent.workflow_id, intent.node_id)
        except V2PersistenceError as error:
            if error.code != "node_not_found":
                raise
            return self._close_without_publication(
                intent,
                "node_result_publication_terminal_conflict",
                now=now,
            )
        provenance = intent.planned_result.asset_metadata.get("generated_asset_provenance")
        expected_revision = (
            provenance.get("node_revision") if isinstance(provenance, dict) else None
        )
        snapshot = member.run_intent_snapshot
        if snapshot is None or expected_revision != snapshot.node_revision:
            return self._abandon(intent, "node_result_publication_source_invalid", now=now)

        try:
            recovered = self._assets.recover_prepared_result(intent.planned_result)
            prepared = intent.prepared_result
            if prepared is None:
                prepared = recovered
                intent = self._intents.promote_prepared(
                    intent.intent_id,
                    prepared_result=prepared,
                    now=now,
                )
            elif not _matches_recovered_object(recovered, prepared):
                return self._abandon(
                    intent,
                    "node_result_publication_object_invalid",
                    now=now,
                )
            lease = self._runtime.claim_lease(
                intent.execution_id,
                intent.node_id,
                owner_id=self._owner_id,
                now=now,
                ttl=timedelta(seconds=60),
            )
            if lease is None:
                return self._defer(intent, "execution_lease_unavailable", now=now)
            if not self._runtime.update_member(
                intent.execution_id,
                intent.node_id,
                state="running",
                phase="publishing",
                now=now,
                expected_lease_generation=lease.generation,
            ):
                return self._defer(intent, "stale_execution_lease", now=now)
            self._committer.commit(
                CanvasExecutionResultCommitCommandV2(
                    workflow_id=intent.workflow_id,
                    execution_id=intent.execution_id,
                    member_id=intent.member_id,
                    node_id=intent.node_id,
                    lease_owner_id=lease.owner_id,
                    lease_generation=lease.generation,
                    logical_result_key=intent.logical_result_key,
                    payload_digest=intent.payload_digest,
                    publication_intent_id=intent.intent_id,
                    publication_recovery_attempt=intent.attempt_count,
                    provider_task_id=prepared.provider_task_id,
                    outcome="succeeded",
                    prepared_result=prepared,
                    committed_at=now,
                )
            )
            return "committed"
        except V2PersistenceError as error:
            if error.code in {
                "node_result_publication_object_invalid",
                "provider_output_invalid",
                "video_native_audio_missing",
            }:
                return self._abandon(intent, error.code, now=now)
            return self._defer(intent, error.code, now=now, lease=lease)

    def _close_without_publication(
        self,
        intent: CanvasResultPublicationIntentV1,
        error_code: str,
        *,
        now: datetime,
    ) -> RecoveryDisposition:
        self._intents.abandon(intent.intent_id, error_code=error_code, now=now)
        self._runtime.reconcile_terminal_leases(intent.execution_id, now=now)
        return "abandoned"

    def _defer(
        self,
        intent: CanvasResultPublicationIntentV1,
        error_code: str,
        *,
        now: datetime,
        lease: NodeExecutionLeaseV2 | None = None,
    ) -> RecoveryDisposition:
        if intent.attempt_count >= 15 or now >= intent.recovery_deadline:
            return self._abandon(
                intent,
                "node_result_publication_recovery_exhausted",
                now=now,
                lease=lease,
            )
        delay = min(2 ** min(intent.attempt_count, 5), 30)
        next_attempt = min(now + timedelta(seconds=delay), intent.recovery_deadline)
        try:
            self._intents.defer(
                intent.intent_id,
                expected_attempt_count=intent.attempt_count,
                next_attempt_at=next_attempt,
                error_code=error_code,
                now=now,
            )
        except V2PersistenceError as error:
            if error.code != "node_result_publication_transition_conflict":
                raise
            current = self._intents.get(intent.intent_id)
            if current is not None and current.state == "committed":
                return "committed"
            if current is not None and current.state == "abandoned":
                return "abandoned"
            if current is not None and current.attempt_count > intent.attempt_count:
                return "deferred"
            raise
        return "deferred"

    def _abandon(
        self,
        intent: CanvasResultPublicationIntentV1,
        error_code: str,
        *,
        now: datetime,
        lease: NodeExecutionLeaseV2 | None = None,
    ) -> RecoveryDisposition:
        if lease is None:
            lease = self._runtime.claim_lease(
                intent.execution_id,
                intent.node_id,
                owner_id=self._owner_id,
                now=now,
                ttl=timedelta(seconds=60),
            )
        if lease is None:
            if now < intent.recovery_deadline and intent.attempt_count < 15:
                return self._defer(intent, "execution_lease_unavailable", now=now)
            return "deferred"
        terminal_code = (
            "node_result_publication_recovery_exhausted"
            if error_code == "node_result_publication_recovery_exhausted"
            else "node_result_publication_failed"
        )
        detail = CanvasNodeErrorV2(
            code=terminal_code,
            message="Prepared media could not be published safely.",
            retryable=False,
        )
        failure_key = f"{intent.logical_result_key}:publication-recovery-failed"
        failure_digest = hashlib.sha256(detail.model_dump_json().encode("utf-8")).hexdigest()
        self._committer.commit(
            CanvasExecutionResultCommitCommandV2(
                workflow_id=intent.workflow_id,
                execution_id=intent.execution_id,
                member_id=intent.member_id,
                node_id=intent.node_id,
                lease_owner_id=lease.owner_id,
                lease_generation=lease.generation,
                logical_result_key=failure_key,
                payload_digest=failure_digest,
                outcome="failed",
                error=detail,
                committed_at=now,
            )
        )
        self._intents.abandon(intent.intent_id, error_code=error_code, now=now)
        return "abandoned"


def _matches_recovered_object(
    recovered: PreparedNodeResultV2,
    prepared: PreparedNodeResultV2,
) -> bool:
    """Compare object-derived fields while retaining persisted post-object effects."""

    return (
        recovered.model_copy(
            update={
                "provider_task_id": prepared.provider_task_id,
                "post_ready_effects": prepared.post_ready_effects,
            }
        )
        == prepared
    )
