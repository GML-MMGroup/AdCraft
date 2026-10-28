"""Start Guided Editing as soon as the planned media is complete."""

from __future__ import annotations

from typing import Protocol

from app.persistence.errors import V2PersistenceError

_AUDIO_REQUIRED_OUTCOMES = frozenset({"include", "delegate"})


class _Conversations(Protocol):
    def get_guidance_session_or_none(self, workflow_id: str): ...

    def get_latest_turn(self, workflow_id: str): ...


class _Plans(Protocol):
    def list_plans(self, workflow_id: str): ...


class _Workflows(Protocol):
    def get_workflow(self, workflow_id: str): ...


class _NextActionDispatch(Protocol):
    def dispatch(
        self,
        source_turn,
        *,
        session_id: str,
        expected_session_revision: int,
        objective: str,
    ): ...


class GuidedEditingTrigger:
    """Queue the next Journey action once every planned Video and the BGM are Ready.

    Editing preparation only runs inside a durable Next Action. A manual media
    run resumes its wait but queues no successor (production incident
    2026-10-27), so the last Ready result must start the Journey again. The
    Journey policy still owns the stage transition and Editing preparation.
    """

    def __init__(
        self,
        *,
        conversations: _Conversations,
        plans: _Plans,
        workflows: _Workflows,
        next_action_dispatch: _NextActionDispatch,
    ) -> None:
        self._conversations = conversations
        self._plans = plans
        self._workflows = workflows
        self._next_action_dispatch = next_action_dispatch

    def continue_when_media_complete(self, workflow_id: str) -> bool:
        session = self._conversations.get_guidance_session_or_none(workflow_id)
        if not _journey_is_idle(session):
            return False
        nodes = {node.node_id: node for node in self._workflows.get_workflow(workflow_id).nodes}
        if any(node.node_type == "editing" for node in nodes.values()):
            return False
        required = _required_media_node_ids(self._plans.list_plans(workflow_id).items, session)
        if not required or not all(_is_ready(nodes.get(node_id)) for node_id in required):
            return False
        source_turn = self._conversations.get_latest_turn(workflow_id)
        if source_turn is None:
            return False
        try:
            self._next_action_dispatch.dispatch(
                source_turn,
                session_id=session.session_id,
                expected_session_revision=session.revision,
                objective=session.goal.summary,
            )
        except V2PersistenceError as error:
            if error.code == "guidance_revision_conflict":
                return False
            raise
        return True


def _journey_is_idle(session) -> bool:
    if session is None or session.status != "active" or session.awaiting is not None:
        return False
    journey = session.journey
    if journey.stage == "intake":
        return False
    if journey.active_action is not None or journey.suspended_action is not None:
        return False
    completion = getattr(session, "completion", None)
    return getattr(completion, "editing_preparation", None) != "prepared"


def _required_media_node_ids(plans, session) -> tuple[str, ...]:
    """Return the planned Video and BGM nodes, or () while the plan is incomplete."""

    for plan in plans:
        content = plan.content
        records = tuple(
            getattr(content, "planned_nodes", None) or getattr(content, "node_records", ())
        )
        if not any(record.node_role == "video_segment" for record in records):
            continue
        excluded = tuple(getattr(content, "excluded_media", ()))
        required: list[str] = []
        for segment in content.segments:
            if any(
                item.node_role == "video_segment" and item.sequence_id == segment.sequence_id
                for item in excluded
            ):
                continue
            record = next(
                (
                    item
                    for item in records
                    if item.node_role == "video_segment" and item.sequence_id == segment.sequence_id
                ),
                None,
            )
            if record is None:
                return ()
            required.append(record.node_id)
        if _audio_required(session) and not any(item.node_role == "bgm" for item in excluded):
            bgm = next((item for item in records if item.node_role == "bgm"), None)
            if bgm is None:
                return ()
            required.append(bgm.node_id)
        return tuple(required)
    return ()


def _audio_required(session) -> bool:
    outcomes = {
        decision.outcome
        for decision in session.journey.decisions
        if decision.element_kind == "audio"
    }
    if "unresolved" in outcomes:
        return True
    return bool(outcomes & _AUDIO_REQUIRED_OUTCOMES)


def _is_ready(node) -> bool:
    return node is not None and node.status == "ready" and node.output_asset_id is not None
