from __future__ import annotations

from typing import Any, Protocol


SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS = {5, 10}
SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS = max(SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS)
ARK_SEEDANCE_RESOLUTION = "480p"
DEFAULT_VIDEO_RATIO = "16:9"
SEEDREAM_MIN_IMAGE_PIXELS = 3_686_400


class MediaConfigurationError(RuntimeError):
    """Raised when a media provider cannot be configured."""


class MediaApiError(ValueError):
    """Raised when a real media API returns an error response."""

    def __init__(self, message: str, metadata: dict[str, Any]) -> None:
        super().__init__(message)
        self.metadata = metadata


class MediaProvider(Protocol):
    mode: str

    def generate_storyboard_images(
        self,
        storyboard_scenes: list[dict[str, Any]],
        workflow_id: str,
        input_assets: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def generate_scene_reference_images(
        self,
        scene_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_product_images(
        self,
        product_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_v2_canonical_image(
        self,
        request: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_storyboard_video(
        self,
        storyboard_video_prompt: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_character_turnaround_images(
        self,
        character_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_subtitle_asset(
        self,
        script: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_audio_assets(
        self,
        sound_effects_plan: dict[str, Any],
        voiceover_plan: dict[str, Any],
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_bgm_audio(
        self,
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_final_video_from_multimodal_prompt(
        self,
        final_video_prompt: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def synchronize_audio_video(
        self,
        video_asset: dict[str, Any],
        audio_asset: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def compose_final_video(
        self,
        synchronized_asset: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]: ...
