"""Deterministic worker for accepted Agent Canvas Proposal options."""

from __future__ import annotations

from collections.abc import Callable

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationContextV1,
    CapabilityMaterializationExecutionResultV1,
    ProposalPublicationEnvelopeV1,
)
from app.services.agent_canvas_draft_seed_renderer import (
    DraftSeedRenderContextV1,
    DraftSeedRendererRegistry,
)


class ProposalPublicationRunner:
    """Load a frozen Seed, render it purely, and publish one transaction."""

    def __init__(
        self,
        *,
        conversations: AgentCanvasConversationRepository,
        context_loader: Callable[
            [ProposalPublicationEnvelopeV1], CapabilityMaterializationContextV1
        ],
        publisher: Callable[[ProposalPublicationEnvelopeV1, object, Callable[[], None]], str],
        renderer: DraftSeedRendererRegistry | None = None,
    ) -> None:
        self._conversations = conversations
        self._context_loader = context_loader
        self._publisher = publisher
        self._renderer = renderer or DraftSeedRendererRegistry()

    def execute(
        self,
        envelope: ProposalPublicationEnvelopeV1,
        *,
        lease_guard: Callable[[], None],
    ) -> CapabilityMaterializationExecutionResultV1:
        lease_guard()
        if envelope.draft_seed_schema is None or envelope.draft_seed_digest is None:
            raise _error(
                "proposal_draft_seed_missing",
                "Proposal option has no private Draft Seed; regenerate the Proposal.",
            )
        record = self._conversations.get_draft_seed(envelope.selected_option.option_id)
        if (
            record.draft_seed_schema != envelope.draft_seed_schema
            or record.draft_seed_digest != envelope.draft_seed_digest
        ):
            raise _error(
                "proposal_draft_seed_invalid",
                "Proposal Draft Seed no longer matches the accepted option.",
            )
        seed = self._conversations.get_draft_seed_envelope(envelope.selected_option.option_id)
        if seed.capability_id != envelope.capability_id:
            raise _error(
                "proposal_draft_seed_invalid",
                "Proposal Draft Seed capability is invalid.",
            )
        context = self._context_loader(envelope)
        rendered = self._renderer.render(
            seed,
            DraftSeedRenderContextV1(
                context_snapshot_id=envelope.context_snapshot_id,
                style_prompt=_style_prompt(context),
                style_source=_style_source(context),
            ),
        )
        lease_guard()
        try:
            node_id = self._publisher(envelope, rendered.result, lease_guard)
        except V2PersistenceError:
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


def _style_prompt(context: CapabilityMaterializationContextV1) -> str:
    for key in ("style_prompt", "role_guidance", "summary"):
        value = context.style_projection.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Detailed semi-realistic advertising illustration."


def _style_source(
    context: CapabilityMaterializationContextV1,
) -> str:
    source = context.style_projection.get("source")
    if source in {"user", "video_skill", "references", "platform_default"}:
        return str(source)
    return "video_skill" if context.style_projection else "platform_default"


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="proposal_publication",
        details={"retryable": False},
    )
