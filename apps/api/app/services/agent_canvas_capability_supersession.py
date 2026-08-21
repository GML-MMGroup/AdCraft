"""Deterministic proof that stale guided capability work is obsolete."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from sqlalchemy import select

from app.persistence.database import V2Database
from app.persistence.models import AgentCanvasGuidanceSessionRow
from app.schemas.agent_canvas_capabilities import CapabilityCommandEnvelopeV2
from app.schemas.agent_canvas_production_journey import GuidedProductionJourneyV2, JourneyStageV2
from app.services.agent_canvas_production_journey import FIXED_JOURNEY_STAGE_DESCRIPTORS


@dataclass(frozen=True, slots=True)
class CapabilitySupersessionDecision:
    outcome: Literal["failed", "superseded"]
    envelope_stage: JourneyStageV2 | None = None
    current_stage: JourneyStageV2 | None = None
    current_session_revision: int | None = None


class CapabilitySupersessionClassifier:
    """Classify only revision conflicts proven obsolete by fixed Journey authority."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def classify(
        self,
        envelope: CapabilityCommandEnvelopeV2,
    ) -> CapabilitySupersessionDecision:
        expected_revision = envelope.expected_session_revision
        if expected_revision is None or envelope.session_id is None:
            return CapabilitySupersessionDecision("failed")
        envelope_stage = _envelope_stage(envelope)
        if envelope_stage is None:
            return CapabilitySupersessionDecision("failed")
        with self._database.engine.connect() as connection:
            row = (
                connection.execute(
                    select(AgentCanvasGuidanceSessionRow).where(
                        AgentCanvasGuidanceSessionRow.workflow_id == envelope.workflow_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or str(row["session_id"]) != envelope.session_id:
            return CapabilitySupersessionDecision("failed", envelope_stage=envelope_stage)
        current_revision = int(row["revision"])
        journey = GuidedProductionJourneyV2.model_validate(
            json.loads(str(row["journey_state_json"]))
        )
        if current_revision <= expected_revision:
            return CapabilitySupersessionDecision(
                "failed",
                envelope_stage=envelope_stage,
                current_stage=journey.stage,
                current_session_revision=current_revision,
            )
        current_action = journey.active_action
        if current_action is not None and current_action.turn_id in {
            envelope.source_turn_id,
            envelope.capability_turn_id,
        }:
            return CapabilitySupersessionDecision(
                "failed",
                envelope_stage=envelope_stage,
                current_stage=journey.stage,
                current_session_revision=current_revision,
            )
        stage_order = tuple(FIXED_JOURNEY_STAGE_DESCRIPTORS)
        if stage_order.index(journey.stage) <= stage_order.index(envelope_stage):
            return CapabilitySupersessionDecision(
                "failed",
                envelope_stage=envelope_stage,
                current_stage=journey.stage,
                current_session_revision=current_revision,
            )
        return CapabilitySupersessionDecision(
            "superseded",
            envelope_stage=envelope_stage,
            current_stage=journey.stage,
            current_session_revision=current_revision,
        )


def _envelope_stage(envelope: CapabilityCommandEnvelopeV2) -> JourneyStageV2 | None:
    if envelope.journey_stage is not None:
        descriptor = FIXED_JOURNEY_STAGE_DESCRIPTORS[envelope.journey_stage]
        return (
            envelope.journey_stage if descriptor.capability_id == envelope.capability_id else None
        )
    matches = tuple(
        stage
        for stage, descriptor in FIXED_JOURNEY_STAGE_DESCRIPTORS.items()
        if descriptor.capability_id == envelope.capability_id
    )
    return matches[0] if len(matches) == 1 else None
