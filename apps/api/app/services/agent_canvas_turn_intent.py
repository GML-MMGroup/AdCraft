"""Lean user-intent classification for Agent Canvas turns."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capabilities import (
    TurnIntentContextV2,
    TurnIntentDecisionV2,
)
from app.services.response_locale_resolver import ResponseLocaleResolverV1


class TurnIntentGateway(Protocol):
    def classify_turn_intent(
        self,
        context: TurnIntentContextV2,
        *,
        turn_id: str,
    ) -> TurnIntentDecisionV2: ...


class TurnIntentService:
    """Invoke the one lean classification boundary for a user message."""

    def __init__(
        self,
        gateway: TurnIntentGateway,
        *,
        response_locale_resolver: ResponseLocaleResolverV1 | None = None,
    ) -> None:
        self._gateway = gateway
        self._response_locale_resolver = response_locale_resolver or ResponseLocaleResolverV1()

    def decide(
        self,
        context: TurnIntentContextV2,
        *,
        turn_id: str,
    ) -> TurnIntentDecisionV2:
        try:
            decision = TurnIntentDecisionV2.model_validate(
                self._gateway.classify_turn_intent(context, turn_id=turn_id)
            )
        except ValidationError as error:
            raise V2PersistenceError(
                "turn_intent_contract_invalid",
                "Turn intent remained invalid after structured repair.",
                stage="turn_intent",
            ) from error
        resolved_locale = self._response_locale_resolver.resolve(
            decision.response_locale,
            prior_locale=context.current_response_locale,
        )
        return decision.model_copy(update={"response_locale": resolved_locale})
