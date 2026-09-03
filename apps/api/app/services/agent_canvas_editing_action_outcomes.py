"""Classify blocked Editing preparation against current durable authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from app.persistence.agent_canvas_auto_run_repository import (
    AgentCanvasAutomaticRunRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_execution_settings_repository import (
    AgentCanvasExecutionSettingsRepository,
)
from app.persistence.agent_canvas_guided_interaction_repository import (
    AgentCanvasGuidedInteractionRepository,
)
from app.persistence.agent_canvas_post_ready_repository import (
    AgentCanvasPostReadyEffectRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_guided_interactions import GuidanceAwaitingV2
from app.schemas.agent_canvas_production_closure import (
    EditingActionReconciliationOutcomeV1,
    EditingActionSystemOwnerKindV1,
)
from app.services.agent_canvas_guidance_awaiting import GuidanceAwaitingService


@dataclass(frozen=True)
class EditingActionOutcomeResolution:
    session: GuidedSessionStateV2
    outcome: EditingActionReconciliationOutcomeV1
    reason_code: str
    evidence_ids: tuple[str, ...] = ()
    awaiting_id: str | None = None
    awaiting_kind: str | None = None
    system_owner_kind: EditingActionSystemOwnerKindV1 | None = None
    system_owner_id: str | None = None
    error_code: str | None = None


class GuidedEditingActionOutcomeResolver:
    """Resolve one blocker without inventing work or a second lifecycle."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
    ) -> None:
        database = workflows.database
        events = conversations.events
        self._workflows = workflows
        self._conversations = conversations
        self._runtime = AgentCanvasRuntimeRepository(database, events)
        self._automatic = AgentCanvasAutomaticRunRepository(database, events)
        self._post_ready = AgentCanvasPostReadyEffectRepository(database, events)
        self._settings = AgentCanvasExecutionSettingsRepository(database, events)
        self._awaiting = GuidanceAwaitingService(
            AgentCanvasGuidedInteractionRepository(database, events),
            conversations,
        )

    def resolve(
        self,
        error: V2PersistenceError,
        session: GuidedSessionStateV2,
    ) -> EditingActionOutcomeResolution:
        current = self._conversations.get_guidance_session(session.workflow_id)
        if current.awaiting is not None and current.awaiting.kind in {
            "media_review",
            "manual_node_run",
        }:
            return EditingActionOutcomeResolution(
                session=current,
                outcome="waiting_user",
                reason_code=f"editing_requires_{current.awaiting.kind}",
                evidence_ids=(current.awaiting.awaiting_id, *current.awaiting.node_ids),
                awaiting_id=current.awaiting.awaiting_id,
                awaiting_kind=current.awaiting.kind,
            )
        session = current
        blockers = _blockers(error)
        workflow = self._workflows.get_workflow(session.workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        specific = tuple(
            blocker
            for blocker in blockers
            if isinstance(blocker.get("node_id"), str) and blocker["node_id"] in nodes
        )

        hard = next(
            (
                blocker
                for blocker in _ordered(specific)
                if blocker.get("kind") in {"failed", "missing", "unreadable"}
            ),
            None,
        )
        if hard is not None:
            return self._failed(error, session, hard)

        owners = tuple(
            owner
            for blocker in _ordered(specific)
            if (owner := self._owner(session.workflow_id, str(blocker["node_id"]))) is not None
        )
        unowned_drafts = tuple(
            str(blocker["node_id"])
            for blocker in _ordered(specific)
            if blocker.get("kind") in {"not_ready", "nonterminal_work"}
            and nodes[str(blocker["node_id"])].status == "draft"
            and self._owner(session.workflow_id, str(blocker["node_id"])) is None
        )
        if unowned_drafts:
            settings = self._settings.get_or_create_manual(
                session.workflow_id,
                now=datetime.now(timezone.utc),
            )
            if settings.media_execution_mode == "manual":
                return self._enter_manual_wait(session, unowned_drafts)
            return EditingActionOutcomeResolution(
                session=session,
                outcome="failed",
                reason_code="automatic_editing_work_orphaned",
                evidence_ids=unowned_drafts,
                error_code="guided_editing_automatic_work_orphaned",
            )
        if owners:
            owner_kind, owner_id = sorted(
                owners, key=lambda item: (_OWNER_ORDER[item[0]], item[1])
            )[0]
            return EditingActionOutcomeResolution(
                session=session,
                outcome="system_deferred",
                reason_code="editing_work_owned",
                evidence_ids=(owner_id,),
                system_owner_kind=owner_kind,
                system_owner_id=owner_id,
            )
        return self._failed(error, session, specific[0] if specific else None)

    def _owner(
        self,
        workflow_id: str,
        node_id: str,
    ) -> tuple[EditingActionSystemOwnerKindV1, str] | None:
        for member in self._runtime.list_latest_members_for_workflow(workflow_id):
            if member.node_id == node_id and member.state in {"queued", "waiting", "running"}:
                return "execution_member", member.member_id
        for command in self._automatic.list_for_workflow(workflow_id):
            if command.node_id == node_id and command.state in {"pending", "claimed"}:
                return "automatic_run", command.command_id
        for effect in self._post_ready.list_for_workflow(workflow_id):
            if effect.node_id == node_id and effect.status in {"queued", "running"}:
                return "post_ready_effect", effect.effect_id
        return None

    def _enter_manual_wait(
        self,
        session: GuidedSessionStateV2,
        node_ids: tuple[str, ...],
    ) -> EditingActionOutcomeResolution:
        action = session.journey.active_action
        if action is None:
            return EditingActionOutcomeResolution(
                session=session,
                outcome="superseded",
                reason_code="editing_action_superseded",
            )
        identity = f"{session.workflow_id}:{action.action_id}:{action.stage_revision}"
        digest = sha256(identity.encode()).hexdigest()[:24]
        awaiting = GuidanceAwaitingV2(
            awaiting_id=f"awaiting_editing_{digest}",
            workflow_id=session.workflow_id,
            session_id=session.session_id,
            checkpoint_id=f"editing-node-run:{digest}",
            kind="manual_node_run",
            requires_user_action=True,
            resume_policy="node_terminal",
            node_ids=node_ids,
            stage="editing",
            stage_revision=action.stage_revision,
            created_at=datetime.now(timezone.utc),
        )
        persisted = self._awaiting.enter_manual_node_run(
            awaiting,
            expected_session_revision=session.revision,
            next_action_requires_ready_media=True,
            user_requested_pause=False,
        )
        current = self._conversations.get_guidance_session(session.workflow_id)
        return EditingActionOutcomeResolution(
            session=current,
            outcome="waiting_user",
            reason_code="editing_requires_manual_node_run",
            evidence_ids=(persisted.awaiting_id, *node_ids),
            awaiting_id=persisted.awaiting_id,
            awaiting_kind="manual_node_run",
        )

    @staticmethod
    def _failed(
        error: V2PersistenceError,
        session: GuidedSessionStateV2,
        blocker: dict[str, object] | None,
    ) -> EditingActionOutcomeResolution:
        evidence = _safe_ids(error, blocker)
        error_code = (
            str(blocker.get("error_code"))
            if blocker is not None and isinstance(blocker.get("error_code"), str)
            else error.code
        )
        return EditingActionOutcomeResolution(
            session=session,
            outcome="failed",
            reason_code="editing_preparation_failed",
            evidence_ids=evidence,
            error_code=error_code,
        )


_OWNER_ORDER: dict[EditingActionSystemOwnerKindV1, int] = {
    "execution_member": 0,
    "automatic_run": 1,
    "post_ready_effect": 2,
    "guided_media_resume": 3,
}


def _blockers(error: V2PersistenceError) -> tuple[dict[str, object], ...]:
    value = error.details.get("blockers")
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _ordered(blockers: tuple[dict[str, object], ...]) -> tuple[dict[str, object], ...]:
    priority = {
        "failed": 0,
        "missing": 1,
        "unreadable": 2,
        "not_ready": 3,
        "nonterminal_work": 4,
        "unconfirmed": 5,
    }
    return tuple(
        sorted(
            blockers,
            key=lambda item: (
                priority.get(str(item.get("kind")), 99),
                str(item.get("node_id") or ""),
                str(item.get("error_code") or ""),
            ),
        )
    )


def _safe_ids(
    error: V2PersistenceError,
    blocker: dict[str, object] | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if blocker is not None:
        node_id = blocker.get("node_id")
        if isinstance(node_id, str) and node_id:
            values.append(node_id)
    plan_document_id = error.details.get("plan_document_id")
    if isinstance(plan_document_id, str) and plan_document_id:
        values.append(plan_document_id)
    return tuple(dict.fromkeys(values))[:16]
