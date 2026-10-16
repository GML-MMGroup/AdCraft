"""Structured authorization gate for starting a fresh advertising journey."""

from __future__ import annotations

from app.schemas.agent_canvas_capabilities import TurnIntentDecisionV2


def advertising_production_is_ready(
    decision: TurnIntentDecisionV2,
    *,
    session_exists: bool,
) -> bool:
    """Return whether this turn may create a fresh guided production session.

    The semantic Agent owns the readiness classification. Python only applies the
    typed result and exempts an already-existing session from re-authorization.
    No user-language phrase matching belongs in this gate.
    """

    if decision.mode != "guided_production" or session_exists:
        return True
    return decision.production_readiness == "ready"
