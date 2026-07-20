from agno.models.openai import OpenAIChat

from app.core.config import Settings
from app.core.llm_call_policy import V2LLMCallPolicyResolver


def build_llm_chat_model(
    settings: Settings,
    model_id: str,
    *,
    stage_name: str = "agent_default",
) -> OpenAIChat:
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY is required when AGNO_MOCK_MODE=false.")

    policy = V2LLMCallPolicyResolver(
        transient_retry_delay_seconds=settings.llm_transient_retry_delay_seconds
    ).resolve(
        provider_id=settings.llm_provider,
        stage_name=stage_name,
        attempt_kind="initial",
    )
    extra_body = dict(policy.provider_request_options) or None
    return OpenAIChat(
        id=model_id,
        name="OpenAICompatibleChat",
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=policy.timeout_seconds,
        max_tokens=policy.max_output_tokens,
        retries=0,
        max_retries=policy.sdk_max_retries,
        extra_body=extra_body,
        role_map={
            "system": "system",
            "user": "user",
            "assistant": "assistant",
            "tool": "tool",
            "model": "assistant",
        },
    )
