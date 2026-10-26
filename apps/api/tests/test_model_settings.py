"""An explicit empty model setting must not silently regain an installation default."""

import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    ("environment_name", "settings_field"),
    [
        ("LLM_FRONT_DESK_MODEL", "llm_front_desk_model"),
        ("LLM_TEAM_MODEL", "llm_team_model"),
        ("IMAGE_GENERATION_MODEL", "image_generation_model"),
        ("VIDEO_GENERATION_MODEL", "video_generation_model"),
        ("BGM_MODEL", "bgm_model"),
        ("BGM_LONG_MODEL", "bgm_long_model"),
    ],
)
def test_explicit_empty_model_setting_is_preserved(monkeypatch, environment_name, settings_field):
    monkeypatch.setenv(environment_name, "")
    assert getattr(Settings.from_env(), settings_field) == ""


@pytest.mark.parametrize(
    ("environment_name", "settings_field"),
    [("BGM_MODEL", "bgm_model"), ("BGM_LONG_MODEL", "bgm_long_model")],
)
def test_omitted_audio_model_uses_installation_default(monkeypatch, environment_name, settings_field):
    monkeypatch.delenv(environment_name, raising=False)
    assert getattr(Settings.from_env(), settings_field) == getattr(Settings(), settings_field)
