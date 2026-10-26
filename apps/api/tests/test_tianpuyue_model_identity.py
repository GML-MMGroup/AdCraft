"""Canonical BGM identities must survive selection and submit serialization."""

from dataclasses import replace
import json
import socket

import httpx
import pytest

from app.core.config import Settings
from app.tools.media_provider_protocol import MediaConfigurationError
from app.tools.tianpuyue_pure_music import (
    TianpuyuePureMusicAdapter,
    select_frozen_tianpuyue_instrumental_model,
    select_tianpuyue_instrumental_model,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("Model identity tests must not contact a provider")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)


@pytest.fixture
def settings():
    return Settings(
        bgm_api_key="test-placeholder",
        bgm_callback_mode="manual",
        bgm_callback_base_url="https://callback.example.invalid",
    )


def submit(settings, tmp_path, *, duration, frozen=None):
    bodies = []

    def receive(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": 200000,
                "message": "Test transport only",
                "data": {"item_ids": ["local-test-no-provider-task"]},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(receive)) as client:
        adapter = TianpuyuePureMusicAdapter(
            settings,
            tmp_path,
            client=client,
            callback_id_factory=lambda: "test-callback",
        )
        plan = {"provider_prompt": "Instrumental product music", "duration_seconds": duration}
        if frozen is not None:
            plan["provider_model_id"] = frozen
        result = adapter.generate_bgm_audio(plan, "adwf_v2_identity_test")
    return result, bodies


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize(
    ("field", "configured", "duration", "native_id", "wire_model"),
    [
        ("bgm_model", "TemPolor i3", 60, "TemPolor-i3", "TemPolor i3"),
        ("bgm_model", "TemPolor-i3", 60, "TemPolor-i3", "TemPolor i3"),
        ("bgm_model", "tianpuyue:TemPolor-i3", 60, "TemPolor-i3", "TemPolor i3"),
        ("bgm_long_model", "TemPolor i3.5", 180, "TemPolor-i3.5", "TemPolor i3.5"),
        ("bgm_long_model", "TemPolor-i3.5", 180, "TemPolor-i3.5", "TemPolor i3.5"),
        ("bgm_long_model", "tianpuyue:TemPolor-i3.5", 180, "TemPolor-i3.5", "TemPolor i3.5"),
    ],
)
def test_exact_aliases_preserve_identity_in_submit_payload(
    settings, tmp_path, frozen, field, configured, duration, native_id, wire_model
):
    configured_settings = replace(settings, **{field: configured})
    selection = (
        select_frozen_tianpuyue_instrumental_model(native_id, duration, configured_settings)
        if frozen
        else select_tianpuyue_instrumental_model(duration, configured_settings)
    )
    assert selection.model == wire_model
    result, bodies = submit(
        configured_settings, tmp_path, duration=duration, frozen=native_id if frozen else None
    )
    assert result["status"] == "submitted"
    assert len(bodies) == 1
    assert bodies[0]["model"] == wire_model
    assert result["provider_wire_model"] == wire_model
    if frozen:
        assert result["frozen_provider_model_id"] == native_id


def test_frozen_long_model_is_not_downgraded_for_short_duration(settings, tmp_path):
    configured = replace(settings, bgm_long_model="tianpuyue:TemPolor-i3.5")
    result, bodies = submit(configured, tmp_path, duration=60, frozen="TemPolor-i3.5")
    assert result["status"] == "submitted"
    assert bodies[0]["model"] == "TemPolor i3.5"


@pytest.mark.parametrize(
    "configured",
    ["TemPolor i3.5", "TemPolor-i3.5", "other-provider:TemPolor-i3", "unknown-model-260999"],
)
def test_configuration_cannot_replace_a_frozen_model(settings, tmp_path, configured):
    result, bodies = submit(
        replace(settings, bgm_model=configured), tmp_path, duration=60, frozen="TemPolor-i3"
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "bgm_provider_model_mismatch"
    assert bodies == []


def test_unknown_legacy_duration_model_is_not_guessed(settings, tmp_path):
    unknown = "unknown-model-260999"
    result, bodies = submit(replace(settings, bgm_model=unknown), tmp_path, duration=60)
    assert result["status"] == "submitted"
    assert bodies[0]["model"] == unknown


def test_unknown_frozen_model_is_not_guessed(settings, tmp_path):
    result, bodies = submit(settings, tmp_path, duration=60, frozen="TemPolor-i3-260999")
    assert result["status"] == "failed"
    assert result["error_code"] == "bgm_provider_model_unsupported"
    assert bodies == []


def test_frozen_short_model_is_not_upgraded_for_long_duration(settings, tmp_path):
    result, bodies = submit(settings, tmp_path, duration=121, frozen="TemPolor-i3")
    assert result["status"] == "failed"
    assert result["error_code"] == "bgm_duration_unsupported"
    assert bodies == []


@pytest.mark.parametrize(("field", "duration"), [("bgm_model", 60), ("bgm_long_model", 180)])
def test_empty_configuration_remains_an_error(settings, field, duration):
    with pytest.raises(MediaConfigurationError):
        select_tianpuyue_instrumental_model(duration, replace(settings, **{field: ""}))
