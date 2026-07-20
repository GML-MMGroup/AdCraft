from __future__ import annotations

from app.schemas.workflow_v2_prompt_eval import (
    V2PromptProfile,
    V2PromptProfilePayloadInjection,
)


class V2PromptProfileError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2PromptProfileRegistry:
    def __init__(self, profiles: list[V2PromptProfile] | None = None) -> None:
        built_ins = profiles or _built_in_profiles()
        self._profiles = {profile.profile_id: profile for profile in built_ins}

    def list(self) -> list[V2PromptProfile]:
        return [self._profiles[key] for key in sorted(self._profiles)]

    def get(self, profile_id: str) -> V2PromptProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise V2PromptProfileError(
                "prompt_eval_profile_not_found",
                f"Prompt eval profile not found: {profile_id}",
            ) from exc


def _built_in_profiles() -> list[V2PromptProfile]:
    return [
        V2PromptProfile(
            profile_id="current",
            title="Current",
            description="Current backend V2 prompt stack without prompt mutations.",
        ),
        V2PromptProfile(
            profile_id="candidate",
            title="Candidate",
            description="Candidate prompt profile used for deterministic A/B replay.",
            specialist_prompt_suffix=(
                " Maintain slot-specific visual continuity and provider-safe reference summaries."
            ),
        ),
        V2PromptProfile(
            profile_id="unsafe_candidate",
            title="Unsafe Candidate",
            description="Test-only profile that injects an unsafe payload field for regression gates.",
            provider_payload_injections=[
                V2PromptProfilePayloadInjection(
                    key="api_key",
                    value="unsafe-test-secret",
                    stages=["provider_payload"],
                )
            ],
        ),
    ]
