"""In-memory credential delivery for the private Pi Agent runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings
from app.schemas.agent_runtime import AgentName


_AGENT_OPERATIONS: dict[AgentName, frozenset[str]] = {
    "front_desk": frozenset({"workflow_creation", "intent_contract_planner"}),
    "script_writer": frozenset({"script_writer", "script_edit_normalization", "targeted_revision"}),
    "product_designer": frozenset(
        {
            "product_expert_brief",
            "product_prompt",
            "product_revision",
            "targeted_revision",
        }
    ),
    "character_designer": frozenset(
        {
            "character_expert_brief",
            "character_prompt",
            "character_revision",
            "targeted_revision",
        }
    ),
    "scene_designer": frozenset(
        {
            "scene_expert_brief",
            "scene_prompt",
            "scene_revision",
            "visual_style_scope_repair",
            "targeted_revision",
        }
    ),
    "storyboard_artist": frozenset({"storyboard_detail", "storyboard_prompt", "targeted_revision"}),
    "video_director": frozenset({"shot_video_prompt", "targeted_revision"}),
    "bgm_director": frozenset({"bgm_expert_brief", "bgm_prompt", "targeted_revision"}),
    "quick_media_agent": frozenset({"free_image", "free_video", "free_audio"}),
}


class AgentCredentialError(RuntimeError):
    """Stable credential lookup failure that never embeds a credential value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentCredentialSnapshot:
    protocol_version: str
    provider: str
    model_id: str
    model_policy_id: str
    base_url: str
    api_key: str = field(repr=False)


class V2AgentCredentialBroker:
    """Resolve one allowlisted runtime credential reference from current settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def snapshot(
        self,
        credential_ref: str,
        *,
        agent_name: AgentName,
        operation: str,
        model_policy_id: str,
    ) -> AgentCredentialSnapshot:
        if credential_ref != "llm-default":
            raise AgentCredentialError(
                "agent_credential_ref_unknown",
                "Agent runtime credential reference is not registered.",
            )
        if operation not in _AGENT_OPERATIONS[agent_name]:
            raise AgentCredentialError(
                "agent_operation_not_allowed",
                "Agent runtime operation is not registered for this Agent.",
            )
        expected_policy_id = f"{agent_name}.{operation}.v1"
        if model_policy_id != expected_policy_id:
            raise AgentCredentialError(
                "agent_model_policy_mismatch",
                "Agent runtime model policy does not match the requested operation.",
            )
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise AgentCredentialError(
                "agent_model_unavailable",
                "The configured text model is unavailable.",
            )
        return AgentCredentialSnapshot(
            protocol_version=self._settings.agent_runtime_protocol_version,
            provider=self._settings.llm_provider,
            model_id=_model_for_agent(self._settings, agent_name),
            model_policy_id=model_policy_id,
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
        )


def _model_for_agent(settings: Settings, agent_name: AgentName) -> str:
    return {
        "front_desk": settings.llm_front_desk_model,
        "script_writer": settings.llm_script_model,
        "product_designer": settings.llm_product_design_model,
        "character_designer": settings.llm_character_model,
        "scene_designer": settings.llm_scene_model,
        "storyboard_artist": settings.llm_storyboard_model,
        "video_director": settings.llm_final_video_model,
        "bgm_director": settings.llm_bgm_model,
        "quick_media_agent": settings.llm_creative_model,
    }[agent_name]
