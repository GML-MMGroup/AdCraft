"""Structured authorization gate for starting a fresh advertising journey."""

from __future__ import annotations

from app.schemas.agent_canvas_capabilities import TurnIntentDecisionV2


def advertising_production_is_ready(
    decision: TurnIntentDecisionV2,
    *,
    session_exists: bool,
) -> bool:
    """Return whether this turn may create a fresh guided production session.

    The semantic Agent owns intent classification and exact source evidence. Python
    applies the typed readiness and promoted-subject boundary, then exempts an
    already-existing session from re-authorization. No user-language phrase
    matching belongs in this gate.
    """

    if decision.mode != "guided_production" or session_exists:
        return True
    if decision.production_readiness != "ready":
        return False
    return any(
        element.element_kind == "product" and element.presence == "include"
        for element in decision.explicit_elements
    )


def advertising_production_gate_reason(
    decision: TurnIntentDecisionV2,
    *,
    session_exists: bool,
) -> str | None:
    """Return a stable reason when a fresh guided request cannot be admitted."""

    if decision.mode != "guided_production" or session_exists:
        return None
    if decision.production_readiness != "ready":
        return "production_not_authorized"
    if not any(
        element.element_kind == "product" and element.presence == "include"
        for element in decision.explicit_elements
    ):
        return "missing_promoted_subject"
    return None
