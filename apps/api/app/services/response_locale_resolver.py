"""Deterministic product response-locale resolution."""

from __future__ import annotations

from typing import cast

from app.schemas.language import BCP47Tag, canonicalize_bcp47_tag


class ResponseLocaleResolverV1:
    """Resolve validated model locale candidates to durable product locales."""

    policy_id = "response-locale-v1"

    def resolve(
        self,
        effective_locale: BCP47Tag,
        *,
        prior_locale: BCP47Tag | None = None,
    ) -> BCP47Tag:
        effective = canonicalize_bcp47_tag(effective_locale)
        prior = canonicalize_bcp47_tag(prior_locale or "und")
        resolved_prior = "zh-CN" if prior in {"zh", "zh-Hans"} else prior

        if effective == "und":
            return cast(BCP47Tag, resolved_prior)
        if effective == "zh-Hans":
            return cast(BCP47Tag, "zh-CN")
        if effective == "zh":
            if resolved_prior.startswith("zh-"):
                return cast(BCP47Tag, resolved_prior)
            return cast(BCP47Tag, "zh-CN")
        return cast(BCP47Tag, effective)
