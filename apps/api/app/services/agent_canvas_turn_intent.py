"""Lean user-intent classification for Agent Canvas turns."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capabilities import (
    TurnIntentContextV2,
    TurnIntentDecisionV2,
)


class TurnIntentGateway(Protocol):
    def classify_turn_intent(
        self,
        context: TurnIntentContextV2,
        *,
        turn_id: str,
    ) -> TurnIntentDecisionV2: ...


class TurnIntentService:
    """Invoke the one lean classification boundary for a user message."""

    def __init__(self, gateway: TurnIntentGateway) -> None:
        self._gateway = gateway

    def decide(
        self,
        context: TurnIntentContextV2,
        *,
        turn_id: str,
    ) -> TurnIntentDecisionV2:
        try:
            return TurnIntentDecisionV2.model_validate(
                self._gateway.classify_turn_intent(context, turn_id=turn_id)
            )
        except ValidationError as error:
            raise V2PersistenceError(
                "turn_intent_contract_invalid",
                "Turn intent remained invalid after structured repair.",
                stage="turn_intent",
            ) from error
