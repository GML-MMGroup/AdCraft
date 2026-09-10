"""Deterministic user-visible product identity and capability replies."""

from __future__ import annotations

from typing import Literal

from app.schemas.language import BCP47Tag
from app.services.response_locale_resolver import ResponseLocaleResolverV1


class AgentProductInformationReplyRenderer:
    """Render bounded public product facts without exposing runtime internals."""

    policy_id = "agent-product-information-v1"

    def __init__(self, locale_resolver: ResponseLocaleResolverV1 | None = None) -> None:
        self._locale_resolver = locale_resolver or ResponseLocaleResolverV1()

    def render(
        self,
        intent_kind: Literal["agent_identity", "agent_capabilities"],
        *,
        response_locale: BCP47Tag,
    ) -> str:
        locale = self._locale_resolver.resolve(response_locale)
        if locale == "zh-TW":
            return self._render_zh(intent_kind, traditional=True)
        if locale.startswith("zh"):
            return self._render_zh(intent_kind, traditional=False)
        if intent_kind == "agent_identity":
            return (
                "I am the AdCraft Video Agent, the user-facing assistant for creating "
                "video advertising workflows."
            )
        return (
            "I can help develop advertising requirements, scripts, visual designs, "
            "storyboards, video drafts, background music, and editing exports within "
            "the current workflow."
        )

    @staticmethod
    def _render_zh(
        intent_kind: Literal["agent_identity", "agent_capabilities"],
        *,
        traditional: bool,
    ) -> str:
        if intent_kind == "agent_identity":
            if traditional:
                return "我是 AdCraft Video Agent，協助你建立影片廣告工作流程。"
            return "我是 AdCraft Video Agent，帮助你创建视频广告工作流。"
        if traditional:
            return (
                "我可以在目前工作流程中協助整理廣告需求、腳本、視覺設計、"
                "分鏡、影片草稿、背景音樂和剪輯匯出。"
            )
        return (
            "我可以在当前工作流中协助整理广告需求、脚本、视觉设计、分镜、"
            "视频草稿、背景音乐和剪辑导出。"
        )
