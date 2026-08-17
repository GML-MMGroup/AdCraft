"""Deterministic worker for accepted Agent Canvas Proposal options."""

from __future__ import annotations

from collections.abc import Callable

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationContextV1,
    CapabilityMaterializationExecutionResultV1,
    ProposalPublicationEnvelopeV1,
)
from app.services.pi_agent_runtime_client import PiAgentRuntimeError


class ProposalPublicationRunner:
    """Publish visible Drafts from one frozen concise Proposal option."""

    def __init__(
        self,
        *,
        context_loader: Callable[
            [ProposalPublicationEnvelopeV1], CapabilityMaterializationContextV1
        ],
        publisher: Callable[[ProposalPublicationEnvelopeV1, object, Callable[[], None]], str],
        conversations: object | None = None,
    ) -> None:
        del conversations
        self._context_loader = context_loader
        self._publisher = publisher

    def execute(
        self,
        envelope: ProposalPublicationEnvelopeV1,
        *,
        lease_guard: Callable[[], None],
    ) -> CapabilityMaterializationExecutionResultV1:
        lease_guard()
        context = self._context_loader(envelope)
        lease_guard()
        try:
            node_id = self._publisher(envelope, context, lease_guard)
        except (PiAgentRuntimeError, V2PersistenceError):
            raise
        except Exception as error:  # noqa: BLE001 - transaction boundary normalization.
            raise _error(
                "proposal_publication_failed",
                "Proposal publication failed.",
            ) from error
        return CapabilityMaterializationExecutionResultV1(
            materialization_id=envelope.materialization_id,
            node_id=node_id,
            repaired=False,
        )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="proposal_publication",
        details={"retryable": False},
    )
