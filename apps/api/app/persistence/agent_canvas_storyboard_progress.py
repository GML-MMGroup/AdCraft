"""Durable, replay-safe presentation of storyboard segment authoring progress."""

from datetime import datetime, timezone
from hashlib import sha256
import json

from sqlalchemy import func, insert, select

from app.persistence.database import V2Database
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasChatEntryRow, AgentCanvasConceptProposalRow
from app.schemas.agent_canvas_materialization import ProposalApplicationEnvelopeV1
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_user_presentation import build_presentation_metadata


class StoryboardAuthoringProgress:
    """Append delivery evidence without mutating the storyboard or scheduling media."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        self._database = database
        self._events = events

    def publish(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        *,
        attempt_no: int,
        completed: int,
        total: int,
        response_locale: str,
    ) -> None:
        if total < 1 or not 0 <= completed <= total:
            raise ValueError("Invalid storyboard progress counts.")
        key = f"storyboard-progress:{envelope.materialization_id}:{attempt_no}:{total}:{completed}"
        entry_id = f"entry_{sha256(key.encode()).hexdigest()[:32]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            proposal = connection.execute(
                select(AgentCanvasConceptProposalRow).where(
                    AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id,
                    AgentCanvasConceptProposalRow.workflow_id == envelope.workflow_id,
                    AgentCanvasConceptProposalRow.materialization_id == envelope.materialization_id,
                    AgentCanvasConceptProposalRow.materialization_attempt_no == attempt_no,
                    AgentCanvasConceptProposalRow.materialization_status.in_(("queued", "working")),
                )
            ).first()
            existing = connection.execute(
                select(AgentCanvasChatEntryRow.entry_id).where(
                    AgentCanvasChatEntryRow.entry_id == entry_id
                )
            ).first()
            if proposal is None or existing is not None:
                connection.commit()
                return
            if attempt_no > 1:
                retained = connection.execute(
                    select(
                        func.max(
                            func.json_extract(
                                AgentCanvasChatEntryRow.metadata_json, "$.message_args.completed"
                            )
                        )
                    ).where(
                        AgentCanvasChatEntryRow.conversation_id == envelope.conversation_id,
                        func.json_extract(
                            AgentCanvasChatEntryRow.metadata_json, "$.materialization_id"
                        )
                        == envelope.materialization_id,
                        func.json_extract(
                            AgentCanvasChatEntryRow.metadata_json, "$.message_args.total"
                        )
                        == total,
                    )
                ).scalar_one_or_none()
                if isinstance(retained, int) and completed < retained:
                    connection.commit()
                    return
            sequence = (
                1
                + connection.execute(
                    select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                        AgentCanvasChatEntryRow.conversation_id == envelope.conversation_id
                    )
                ).scalar_one()
            )
            status = "preparing_nodes" if completed == total else "working"
            metadata = build_presentation_metadata(
                message_key="storyboard.authoring_progress",
                message_args={"completed": completed, "total": total},
                response_locale=response_locale,
                presentation_key=f"planning:{envelope.materialization_id}",
                base={
                    "type": "storyboard_authoring_progress",
                    "materialization_id": envelope.materialization_id,
                    "proposal_id": envelope.proposal_id,
                    "capability_id": "storyboard_design",
                    "turn_id": envelope.action_turn_id,
                    "attempt": attempt_no,
                    "status": status,
                },
            )
            content = (
                f"Storyboard writing complete: {completed}/{total}. Preparing canvas nodes."
                if completed == total
                else f"Writing storyboard segments: {completed}/{total} complete."
            )
            connection.execute(
                insert(AgentCanvasChatEntryRow).values(
                    entry_id=entry_id,
                    conversation_id=envelope.conversation_id,
                    workflow_id=envelope.workflow_id,
                    sequence_no=sequence,
                    entry_type="planning_progress",
                    speaker="adcraft_video_agent",
                    content=content,
                    metadata_json=json.dumps(metadata),
                    created_at=now,
                )
            )
            self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=envelope.workflow_id,
                    conversation_id=envelope.conversation_id,
                    turn_id=envelope.action_turn_id,
                    event_type="chat_message_created",
                    transition_key=key,
                    created_at=now,
                    payload={
                        "message_id": entry_id,
                        "refresh": ["timeline"],
                        "progress_kind": "storyboard_authoring",
                    },
                ),
            )
            connection.commit()
