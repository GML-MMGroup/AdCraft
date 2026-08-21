"""Deterministic compact projection for public guided concept choices."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import ConceptOptionRecordV2, ConceptProposalV2
from app.schemas.agent_canvas_guided_interactions import GuidedChoiceOptionV1
from app.services.response_locale_resolver import ResponseLocaleResolverV1


_TITLE_LIMIT = 64
_SUMMARY_LIMIT = 240
_SENTENCE_TERMINATORS = frozenset(".!?。！？")


@dataclass(frozen=True, slots=True)
class PublicConceptProjectionV1:
    options: tuple[GuidedChoiceOptionV1, ...]
    response_locale: str


class AgentCanvasPublicConceptProjector:
    """Project private model options into bounded user-facing copies."""

    def __init__(self, locale_resolver: ResponseLocaleResolverV1 | None = None) -> None:
        self._locale_resolver = locale_resolver or ResponseLocaleResolverV1()

    def project(
        self,
        *,
        options: Sequence[object],
        option_ids: Sequence[str],
        response_locale: str,
        recommended_option_id: str,
    ) -> PublicConceptProjectionV1:
        if len(options) != 3 or len(option_ids) != 3 or len(set(option_ids)) != 3:
            raise _error("A public concept requires exactly three unique options.")
        if recommended_option_id not in option_ids:
            raise _error("The recommended public concept option is unavailable.")

        projected = tuple(
            GuidedChoiceOptionV1(
                option_id=option_id,
                title=_compact_text(getattr(option, "title", ""), limit=_TITLE_LIMIT),
                summary=_compact_summary(getattr(option, "public_summary", "")),
                recommended=option_id == recommended_option_id,
            )
            for option_id, option in zip(option_ids, options, strict=True)
        )
        identities = {(item.title.casefold(), item.summary.casefold()) for item in projected}
        if len(identities) != 3:
            raise _error("Public concept options must remain meaningfully distinct.")
        return PublicConceptProjectionV1(
            options=projected,
            response_locale=self._locale_resolver.resolve(response_locale),
        )

    def project_proposal(
        self,
        proposal: ConceptProposalV2,
        *,
        response_locale: str,
    ) -> ConceptProposalV2:
        """Return a public Proposal copy without changing persisted private facts."""

        option_ids = tuple(option.option_id for option in proposal.options)
        projection = self.project(
            options=proposal.options,
            option_ids=option_ids,
            response_locale=response_locale,
            recommended_option_id=option_ids[0],
        )
        return proposal.model_copy(
            update={
                "options": tuple(
                    ConceptOptionRecordV2(
                        option_id=option.option_id,
                        title=option.title,
                        public_summary=option.summary,
                    )
                    for option in projection.options
                )
            }
        )


def public_option_metadata(option: GuidedChoiceOptionV1) -> dict[str, object]:
    """Return the stable Proposal and Timeline metadata representation."""

    return {
        "option_id": option.option_id,
        "title": option.title,
        "public_summary": option.summary,
        "recommended": option.recommended,
    }


def _compact_text(value: object, *, limit: int) -> str:
    text = " ".join(str(value).split())
    if not text:
        raise _error("Public concept text cannot be empty.")
    return text[:limit].rstrip()


def _compact_summary(value: object) -> str:
    text = " ".join(str(value).split())
    if not text:
        raise _error("Public concept summary cannot be empty.")
    sentence_count = 0
    boundary = len(text)
    for index, character in enumerate(text):
        if character not in _SENTENCE_TERMINATORS:
            continue
        sentence_count += 1
        if sentence_count == 2:
            boundary = index + 1
            break
    return _compact_text(text[:boundary], limit=_SUMMARY_LIMIT)


def _error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "capability_presentation_contract_invalid",
        message,
        stage="capability_presentation_projection",
        details={"retryable": False},
    )
