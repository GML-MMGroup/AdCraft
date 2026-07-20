from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_DOTENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_LOCAL_SETTINGS_ALLOWED_ORIGINS = (
    "http://localhost:5189",
    "http://127.0.0.1:5189",
    "http://[::1]:5189",
)


def load_project_dotenv(dotenv_path: Path | None = None) -> bool:
    """Load the project dotenv without replacing explicit process values."""

    return load_dotenv(dotenv_path=dotenv_path or PROJECT_DOTENV_PATH, override=False)


load_project_dotenv()


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _read_path(name: str, default: Path) -> Path:
    path = Path(os.getenv(name, str(default))).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_name: str = "AdCraft"
    app_version: str = "1.0.0"
    agno_mock_mode: bool = False
    v2_production_acceptance_enabled: bool = False
    v2_prompt_materializer_strict: bool = False
    v2_provider_allow_fallback: bool = False
    llm_provider: str = "OpenAI Compatible"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_transient_retry_delay_seconds: float = 2.0
    llm_front_desk_model: str = "doubao-seed-2-0-mini-260428"
    llm_team_model: str = "doubao-seed-2-0-mini-260428"
    llm_requirements_model: str = "doubao-seed-2-0-mini-260428"
    llm_product_design_model: str = "doubao-seed-2-0-mini-260428"
    llm_creative_model: str = "doubao-seed-2-0-mini-260428"
    llm_script_model: str = "doubao-seed-2-0-mini-260428"
    llm_character_model: str = "doubao-seed-2-0-mini-260428"
    llm_scene_model: str = "doubao-seed-2-0-mini-260428"
    llm_storyboard_model: str = "doubao-seed-2-0-mini-260428"
    llm_sound_effects_model: str = "doubao-seed-2-0-mini-260428"
    llm_voiceover_model: str = "doubao-seed-2-0-mini-260428"
    llm_bgm_model: str = "doubao-seed-2-0-mini-260428"
    llm_final_video_model: str = "doubao-seed-2-0-mini-260428"
    media_mode: str = "mock"
    skip_audio_agents: bool = False
    local_settings_allowed_origins: tuple[str, ...] = DEFAULT_LOCAL_SETTINGS_ALLOWED_ORIGINS
    image_generation_api_key: str | None = None
    image_generation_endpoint: str | None = None
    image_generation_model: str = "doubao-seedream-5-0-lite-260128"
    image_generation_size: str = "2048x2048"
    video_generation_api_key: str | None = None
    video_generation_endpoint: str | None = None
    video_generation_model: str = "doubao-seedance-2-0-fast-260128"
    video_generation_resolution: str = "720p"
    video_generation_generate_audio: bool = True
    sound_effects_api_key: str | None = None
    sound_effects_endpoint: str | None = None
    sound_effects_model: str = "volcengine-sound-effects"
    tts_api_key: str | None = None
    tts_endpoint: str | None = None
    tts_model: str = "volcengine-tts"
    bgm_provider: str = "tianpuyue"
    bgm_access_key_id: str | None = None
    bgm_secret_access_key: str | None = None
    bgm_api_key: str | None = None
    bgm_endpoint: str | None = "https://api.tianpuyue.cn"
    bgm_submit_action: str = "GenBGMForTime"
    bgm_api_version: str = "2024-08-12"
    bgm_generation_version: str = "v5.0"
    bgm_model: str | None = "TemPolor i3"
    bgm_long_model: str | None = "TemPolor i3.5"
    bgm_callback_base_url: str | None = None
    bgm_query_endpoint: str | None = None
    bgm_timeout_seconds: int = 60
    bgm_download_max_bytes: int = 100 * 1024 * 1024
    composition_api_key: str | None = None
    composition_endpoint: str | None = None
    composition_provider: str = "ffmpeg"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    final_composition_subtitle_font_path: str | None = None
    ffmpeg_capability_timeout_seconds: int = 10
    ffmpeg_video_codec: str | None = None
    ffmpeg_allowed_video_encoders: str = "libx264,libopenh264"
    keep_intermediate_files: bool = False
    keep_failed_intermediate_files: bool = True
    workflow_max_parallel_nodes: int = 3
    workflow_parallel_scheduler_enabled: bool = True
    provider_max_attempts_image: int = 2
    provider_max_attempts_video: int = 2
    provider_max_attempts_audio: int = 2
    provider_failure_cooldown_threshold: int = 3
    provider_cooldown_seconds: int = 300
    v2_stale_running_timeout_seconds: int = 900
    v2_max_parallel_image_jobs: int = 4
    v2_max_parallel_video_jobs: int = 1
    v2_max_parallel_audio_jobs: int = 1
    v2_max_parallel_generation_jobs: int = 5
    v2_provider_task_poll_interval_seconds: int = 8
    v2_provider_task_max_concurrent_polls: int = 2
    v2_provider_task_timeout_seconds: int = 3600
    v2_provider_download_max_attempts: int = 3
    v2_provider_rate_limit_cooldown_seconds: int = 120
    v2_provider_rate_limit_reduced_image_jobs: int = 2
    v2_provider_rate_limit_reduced_video_jobs: int = 1
    v2_provider_reference_max_data_url_bytes: int = 4 * 1024 * 1024
    v2_provider_reference_total_data_url_bytes: int = 8 * 1024 * 1024
    upload_image_max_bytes: int = 20 * 1024 * 1024
    upload_audio_max_bytes: int = 100 * 1024 * 1024
    upload_video_max_bytes: int = 500 * 1024 * 1024
    media_data_dir: Path = Path("data")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_name=os.getenv("APP_NAME", cls.app_name),
            app_version=os.getenv("APP_VERSION", cls.app_version),
            agno_mock_mode=_read_bool("AGNO_MOCK_MODE", cls.agno_mock_mode),
            v2_production_acceptance_enabled=_read_bool(
                "V2_PRODUCTION_ACCEPTANCE_ENABLED",
                cls.v2_production_acceptance_enabled,
            ),
            v2_prompt_materializer_strict=_read_bool(
                "V2_PROMPT_MATERIALIZER_STRICT",
                cls.v2_prompt_materializer_strict,
            ),
            v2_provider_allow_fallback=_read_bool(
                "V2_PROVIDER_ALLOW_FALLBACK",
                cls.v2_provider_allow_fallback,
            ),
            llm_provider=os.getenv("LLM_PROVIDER", cls.llm_provider),
            llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
            llm_base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None,
            llm_transient_retry_delay_seconds=_read_float(
                "LLM_TRANSIENT_RETRY_DELAY_SECONDS",
                cls.llm_transient_retry_delay_seconds,
            ),
            llm_front_desk_model=os.getenv(
                "LLM_FRONT_DESK_MODEL",
                cls.llm_front_desk_model,
            ),
            llm_team_model=os.getenv("LLM_TEAM_MODEL", cls.llm_team_model),
            llm_requirements_model=os.getenv(
                "LLM_REQUIREMENTS_MODEL",
                cls.llm_requirements_model,
            ),
            llm_product_design_model=os.getenv(
                "LLM_PRODUCT_DESIGN_MODEL",
                cls.llm_product_design_model,
            ),
            llm_creative_model=os.getenv("LLM_CREATIVE_MODEL", cls.llm_creative_model),
            llm_script_model=os.getenv("LLM_SCRIPT_MODEL", cls.llm_script_model),
            llm_character_model=os.getenv("LLM_CHARACTER_MODEL", cls.llm_character_model),
            llm_scene_model=os.getenv("LLM_SCENE_MODEL", cls.llm_scene_model),
            llm_storyboard_model=os.getenv("LLM_STORYBOARD_MODEL", cls.llm_storyboard_model),
            llm_sound_effects_model=(
                os.getenv("LLM_SOUND_EFFECTS_MODEL")
                or os.getenv("LLM_SOUND_MODEL")
                or cls.llm_sound_effects_model
            ),
            llm_voiceover_model=os.getenv("LLM_VOICEOVER_MODEL", cls.llm_voiceover_model),
            llm_bgm_model=os.getenv("LLM_BGM_MODEL", cls.llm_bgm_model),
            llm_final_video_model=os.getenv(
                "LLM_FINAL_VIDEO_MODEL",
                cls.llm_final_video_model,
            ),
            media_mode=os.getenv("MEDIA_MODE", cls.media_mode),
            skip_audio_agents=_read_bool("SKIP_AUDIO_AGENTS", cls.skip_audio_agents),
            local_settings_allowed_origins=_read_csv(
                "LOCAL_SETTINGS_ALLOWED_ORIGINS",
                cls.local_settings_allowed_origins,
            ),
            image_generation_api_key=os.getenv("IMAGE_GENERATION_API_KEY") or None,
            image_generation_endpoint=os.getenv("IMAGE_GENERATION_ENDPOINT") or None,
            image_generation_model=os.getenv(
                "IMAGE_GENERATION_MODEL",
                cls.image_generation_model,
            ),
            image_generation_size=os.getenv(
                "IMAGE_GENERATION_SIZE",
                cls.image_generation_size,
            ),
            video_generation_api_key=os.getenv("VIDEO_GENERATION_API_KEY") or None,
            video_generation_endpoint=os.getenv("VIDEO_GENERATION_ENDPOINT") or None,
            video_generation_model=os.getenv(
                "VIDEO_GENERATION_MODEL",
                cls.video_generation_model,
            ),
            video_generation_resolution=os.getenv(
                "VIDEO_GENERATION_RESOLUTION",
                cls.video_generation_resolution,
            ),
            video_generation_generate_audio=_read_bool(
                "VIDEO_GENERATION_GENERATE_AUDIO",
                cls.video_generation_generate_audio,
            ),
            sound_effects_api_key=os.getenv("SOUND_EFFECTS_API_KEY") or None,
            sound_effects_endpoint=os.getenv("SOUND_EFFECTS_ENDPOINT") or None,
            sound_effects_model=os.getenv("SOUND_EFFECTS_MODEL", cls.sound_effects_model),
            tts_api_key=os.getenv("TTS_API_KEY") or None,
            tts_endpoint=os.getenv("TTS_ENDPOINT") or None,
            tts_model=os.getenv("TTS_MODEL", cls.tts_model),
            bgm_provider=os.getenv("BGM_PROVIDER", cls.bgm_provider),
            bgm_access_key_id=os.getenv("BGM_ACCESS_KEY_ID") or None,
            bgm_secret_access_key=os.getenv("BGM_SECRET_ACCESS_KEY") or None,
            bgm_api_key=os.getenv("BGM_API_KEY") or None,
            bgm_endpoint=os.getenv("BGM_ENDPOINT") or cls.bgm_endpoint,
            bgm_submit_action=os.getenv("BGM_SUBMIT_ACTION", cls.bgm_submit_action),
            bgm_api_version=os.getenv("BGM_API_VERSION", cls.bgm_api_version),
            bgm_generation_version=os.getenv("BGM_GENERATION_VERSION", cls.bgm_generation_version),
            bgm_model=os.getenv("BGM_MODEL") or cls.bgm_model,
            bgm_long_model=os.getenv("BGM_LONG_MODEL") or cls.bgm_long_model,
            bgm_callback_base_url=os.getenv("BGM_CALLBACK_BASE_URL") or None,
            bgm_query_endpoint=os.getenv("BGM_QUERY_ENDPOINT") or None,
            bgm_timeout_seconds=_read_int("BGM_TIMEOUT_SECONDS", cls.bgm_timeout_seconds),
            bgm_download_max_bytes=_read_int("BGM_DOWNLOAD_MAX_BYTES", cls.bgm_download_max_bytes),
            composition_api_key=os.getenv("COMPOSITION_API_KEY") or None,
            composition_endpoint=os.getenv("COMPOSITION_ENDPOINT") or None,
            composition_provider=os.getenv("COMPOSITION_PROVIDER", cls.composition_provider),
            ffmpeg_path=os.getenv("FFMPEG_PATH", cls.ffmpeg_path),
            ffprobe_path=os.getenv("FFPROBE_PATH", cls.ffprobe_path),
            final_composition_subtitle_font_path=(
                os.getenv("FINAL_COMPOSITION_SUBTITLE_FONT_PATH") or None
            ),
            ffmpeg_capability_timeout_seconds=_read_int(
                "FFMPEG_CAPABILITY_TIMEOUT_SECONDS",
                cls.ffmpeg_capability_timeout_seconds,
            ),
            ffmpeg_video_codec=os.getenv("FFMPEG_VIDEO_CODEC") or None,
            ffmpeg_allowed_video_encoders=os.getenv(
                "FFMPEG_ALLOWED_VIDEO_ENCODERS",
                cls.ffmpeg_allowed_video_encoders,
            ),
            keep_intermediate_files=_read_bool(
                "KEEP_INTERMEDIATE_FILES", cls.keep_intermediate_files
            ),
            keep_failed_intermediate_files=_read_bool(
                "KEEP_FAILED_INTERMEDIATE_FILES", cls.keep_failed_intermediate_files
            ),
            workflow_max_parallel_nodes=_read_int(
                "WORKFLOW_MAX_PARALLEL_NODES", cls.workflow_max_parallel_nodes
            ),
            workflow_parallel_scheduler_enabled=_read_bool(
                "WORKFLOW_PARALLEL_SCHEDULER_ENABLED",
                cls.workflow_parallel_scheduler_enabled,
            ),
            provider_max_attempts_image=int(
                os.getenv(
                    "PROVIDER_MAX_ATTEMPTS_IMAGE",
                    str(cls.provider_max_attempts_image),
                )
            ),
            provider_max_attempts_video=int(
                os.getenv(
                    "PROVIDER_MAX_ATTEMPTS_VIDEO",
                    str(cls.provider_max_attempts_video),
                )
            ),
            provider_max_attempts_audio=int(
                os.getenv(
                    "PROVIDER_MAX_ATTEMPTS_AUDIO",
                    str(cls.provider_max_attempts_audio),
                )
            ),
            provider_failure_cooldown_threshold=int(
                os.getenv(
                    "PROVIDER_FAILURE_COOLDOWN_THRESHOLD",
                    str(cls.provider_failure_cooldown_threshold),
                )
            ),
            provider_cooldown_seconds=int(
                os.getenv("PROVIDER_COOLDOWN_SECONDS", str(cls.provider_cooldown_seconds))
            ),
            v2_stale_running_timeout_seconds=_read_int(
                "V2_STALE_RUNNING_TIMEOUT_SECONDS",
                cls.v2_stale_running_timeout_seconds,
            ),
            v2_max_parallel_image_jobs=_read_int(
                "V2_MAX_PARALLEL_IMAGE_JOBS",
                cls.v2_max_parallel_image_jobs,
            ),
            v2_max_parallel_video_jobs=_read_int(
                "V2_MAX_PARALLEL_VIDEO_JOBS",
                cls.v2_max_parallel_video_jobs,
            ),
            v2_max_parallel_audio_jobs=_read_int(
                "V2_MAX_PARALLEL_AUDIO_JOBS",
                cls.v2_max_parallel_audio_jobs,
            ),
            v2_max_parallel_generation_jobs=_read_int(
                "V2_MAX_PARALLEL_GENERATION_JOBS",
                cls.v2_max_parallel_generation_jobs,
            ),
            v2_provider_task_poll_interval_seconds=_read_int(
                "V2_PROVIDER_TASK_POLL_INTERVAL_SECONDS",
                cls.v2_provider_task_poll_interval_seconds,
            ),
            v2_provider_task_max_concurrent_polls=_read_int(
                "V2_PROVIDER_TASK_MAX_CONCURRENT_POLLS",
                cls.v2_provider_task_max_concurrent_polls,
            ),
            v2_provider_task_timeout_seconds=_read_int(
                "V2_PROVIDER_TASK_TIMEOUT_SECONDS",
                cls.v2_provider_task_timeout_seconds,
            ),
            v2_provider_download_max_attempts=max(
                1,
                _read_int(
                    "V2_PROVIDER_DOWNLOAD_MAX_ATTEMPTS",
                    cls.v2_provider_download_max_attempts,
                ),
            ),
            v2_provider_rate_limit_cooldown_seconds=_read_int(
                "V2_PROVIDER_RATE_LIMIT_COOLDOWN_SECONDS",
                cls.v2_provider_rate_limit_cooldown_seconds,
            ),
            v2_provider_rate_limit_reduced_image_jobs=_read_int(
                "V2_PROVIDER_RATE_LIMIT_REDUCED_IMAGE_JOBS",
                cls.v2_provider_rate_limit_reduced_image_jobs,
            ),
            v2_provider_rate_limit_reduced_video_jobs=_read_int(
                "V2_PROVIDER_RATE_LIMIT_REDUCED_VIDEO_JOBS",
                cls.v2_provider_rate_limit_reduced_video_jobs,
            ),
            v2_provider_reference_max_data_url_bytes=_read_int(
                "V2_PROVIDER_REFERENCE_MAX_DATA_URL_BYTES",
                cls.v2_provider_reference_max_data_url_bytes,
            ),
            v2_provider_reference_total_data_url_bytes=_read_int(
                "V2_PROVIDER_REFERENCE_TOTAL_DATA_URL_BYTES",
                cls.v2_provider_reference_total_data_url_bytes,
            ),
            upload_image_max_bytes=int(
                os.getenv("UPLOAD_IMAGE_MAX_BYTES", str(cls.upload_image_max_bytes))
            ),
            upload_audio_max_bytes=int(
                os.getenv("UPLOAD_AUDIO_MAX_BYTES", str(cls.upload_audio_max_bytes))
            ),
            upload_video_max_bytes=int(
                os.getenv("UPLOAD_VIDEO_MAX_BYTES", str(cls.upload_video_max_bytes))
            ),
            media_data_dir=_read_path("MEDIA_DATA_DIR", cls.media_data_dir),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
