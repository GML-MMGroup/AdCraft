"""Guided Product uploads use configured media tools through the public API."""

import json
import os
from pathlib import Path
import shlex
import sqlite3
import struct
import zlib

from fastapi.testclient import TestClient
import pytest

from app.api.v2.endpoints.agent_canvas import create_agent_canvas_runtime
from app.core.config import Settings
from app.main import create_app
from app.persistence.agent_canvas_guided_interaction_repository import (
    AgentCanvasGuidedInteractionRepository,
)
from app.schemas.agent_canvas_creative_session import CreativeGoalV2
from app.schemas.agent_canvas_production_journey import GuidedProductionJourneyV2
from app.services.persistence_bootstrap import PersistenceBootstrapService


pytestmark = pytest.mark.skipif(os.name == "nt", reason="Tool fixtures require a POSIX shell.")


def png_bytes(red: int, green: int, blue: int) -> bytes:
    """Return a real two-by-two RGB PNG without depending on image libraries."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = (b"\x00" + bytes((red, green, blue)) * 2) * 2
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def prepare_product_question(settings: Settings, workflow_id: str):
    """Create genuine session, interaction, awaiting and journey authority offline."""

    runtime = create_agent_canvas_runtime(settings, bootstrap_model_policy=False)
    try:
        session = runtime.conversation_repository.create_guidance_session(
            workflow_id,
            goal=CreativeGoalV2(
                requested_output="image",
                delivery_scope="generated_media",
                summary="Offline Product source upload",
            ),
            element_decisions=(),
            active_style_skill_run_id=None,
        )
        session = runtime.conversation_repository.replace_guidance_journey(
            session.session_id,
            journey=GuidedProductionJourneyV2(stage="product"),
            expected_session_revision=session.revision,
            idempotency_key="offline-product-stage",
            event_type="offline_product_stage_prepared",
            event_payload={},
        )
        return AgentCanvasGuidedInteractionRepository(
            runtime.database, runtime.event_repository
        ).open_product_source_with_journey(
            workflow_id,
            source_turn_id="offline-product-source",
            expected_session_revision=session.revision,
            idempotency_key="offline-product-question",
            input_kind="multiview",
        )
    finally:
        runtime.database.dispose()


def product_commit_request(interaction, asset_versions):
    return {
        "input_kind": "multiview",
        "asset_versions": asset_versions,
        "interaction_id": interaction.interaction_id,
        "expected_interaction_revision": interaction.revision,
        "expected_session_revision": interaction.expected_session_revision,
        "expected_guidance_revision": interaction.content.expected_guidance_revision,
    }


def create_product_api(settings: Settings) -> TestClient:
    """Build an isolated application using its real persistence bootstrap and routes."""

    application = create_app(settings=settings)
    application.state.v2_persistence_state = PersistenceBootstrapService(settings).bootstrap()
    # Do not start unrelated lifespan recovery/generation workers in an upload test.
    return TestClient(application)


def upload_product_views(client: TestClient, workflow_id: str):
    """Upload real PNG bytes, returning immutable identities in visible order."""

    references = []
    for index, color in enumerate(((220, 40, 30), (30, 80, 210))):
        uploaded = client.post(
            f"/api/v2/workflows/{workflow_id}/assets/upload",
            files={"file": (f"view-{index}.png", png_bytes(*color), "image/png")},
            data={"metadata": json.dumps({"media_type": "image", "title": f"View {index}"})},
            headers={"Idempotency-Key": f"offline-product-upload-{index}"},
        )
        assert uploaded.status_code == 201, uploaded.text
        asset = uploaded.json()["asset"]
        references.append({"asset_id": asset["asset_id"], "version_id": asset["version_id"]})
    return references


def _prepare_upload_case(product_api):
    client, settings, _ = product_api
    created = client.post(
        "/api/v2/projects",
        json={"name": "Offline Product upload"},
        headers={"Idempotency-Key": "offline-product-project"},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["workflow_id"]
    interaction = prepare_product_question(settings, workflow_id)
    references = upload_product_views(client, workflow_id)
    return workflow_id, interaction, references, created.headers["etag"]


def _readback(client, workflow_id):
    workflow = client.get(f"/api/v2/workflows/{workflow_id}")
    assets = client.get(f"/api/v2/workflows/{workflow_id}/assets")
    assert workflow.status_code == assets.status_code == 200
    return workflow.json(), assets.json()["assets"]


def _storage_counts(settings):
    path = settings.media_data_dir / "v2" / "adcraft.sqlite3"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "agent_canvas_nodes",
                "assets",
                "asset_versions",
                "agent_canvas_provider_tasks",
                "agent_runs",
            )
        }


@pytest.fixture
def product_api(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("app.services.provider_model_bootstrap.PROJECT_ROOT", tmp_path)
    source = tmp_path / "compiled.png"
    source.write_bytes(png_bytes(20, 100, 180))
    marker = tmp_path / "probe-called"
    ffprobe = tmp_path / "configured-ffprobe"
    facts = {"streams": [{"codec_type": "video", "width": 2, "height": 2}], "format": {}}
    ffprobe.write_text(
        "#!/bin/sh\n"
        f"printf 'called\\n' >> {shlex.quote(str(marker))}\n"
        f"printf '%s\\n' {shlex.quote(json.dumps(facts))}\n"
    )
    ffprobe.chmod(0o700)
    ffmpeg = tmp_path / "configured-ffmpeg"
    ffmpeg.write_text(
        f'#!/bin/sh\nfor output; do :; done\n/bin/cp {shlex.quote(str(source))} "$output"\n'
    )
    ffmpeg.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    settings = Settings(
        media_data_dir=tmp_path / "media",
        agent_runtime_mode="real",
        media_mode="real",
        ffprobe_path=str(ffprobe),
        ffmpeg_path=str(ffmpeg),
    )
    client = create_product_api(settings)
    try:
        yield client, settings, marker
    finally:
        client.close()


@pytest.mark.parametrize("entrypoint", ["direct", "interaction"])
def test_multiview_upload_commit_uses_configured_probe_through_public_api(product_api, entrypoint):
    client, settings, marker = product_api
    workflow_id, interaction, references, etag = _prepare_upload_case(product_api)
    if entrypoint == "direct":
        url = f"/api/v2/workflows/{workflow_id}/guided/product-inputs"
        request = product_commit_request(interaction, references)
        headers = {"If-Match": etag, "Idempotency-Key": "offline-product-commit"}
        expected_status = 200
    else:
        url = interaction.submit_path
        request = {
            "submission_kind": "product_source",
            "expected_interaction_revision": interaction.revision,
            "expected_session_revision": interaction.expected_session_revision,
            "action": {
                "input_kind": "multiview",
                "choice": "upload",
                "handoff_mode": "apply",
                "asset_versions": references,
                "expected_guidance_revision": interaction.content.expected_guidance_revision,
                "question_id": interaction.content.question_id,
            },
        }
        headers = {"Idempotency-Key": "offline-product-submit"}
        expected_status = 202

    response = client.post(url, json=request, headers=headers)
    assert response.status_code == expected_status, response.text
    assert marker.is_file()
    workflow, assets = _readback(client, workflow_id)
    assert len(workflow["nodes"]) == 1
    node = workflow["nodes"][0]
    assert node["creative_role"] == "product"
    assert node["execution_mode"] == "source_only"
    assert node["status"] == "ready"
    assert node["metadata"]["source_input_kind"] == "multiview"
    provenance = node["metadata"]["provenance"]
    assert provenance["kind"] == "upload_compilation"
    assert [
        {"asset_id": item["asset_id"], "version_id": item["version_id"]}
        for item in provenance["ordered_inputs"]
    ] == references
    assert len(assets) == 3
    compiled = next(asset for asset in assets if asset["asset_id"] == node["output_asset_id"])
    assert compiled["source_type"] == "derived"
    assert compiled["width"] == compiled["height"] == 2
    content = client.get(
        f"/api/v2/assets/{compiled['asset_id']}/content", params={"v": compiled["version_id"]}
    )
    assert content.status_code == 200
    assert content.content == png_bytes(20, 100, 180)
    counts = _storage_counts(settings)
    assert counts["agent_canvas_nodes"] == 1
    assert counts["assets"] == counts["asset_versions"] == 3
    assert counts["agent_canvas_provider_tasks"] == counts["agent_runs"] == 0

    replay = client.post(url, json=request, headers=headers)
    assert replay.status_code == expected_status, replay.text
    assert replay.json()["replayed"] is True
    assert _storage_counts(settings) == counts
    replayed_workflow, replayed_assets = _readback(client, workflow_id)
    assert replayed_workflow["revision"] == workflow["revision"]
    assert replayed_workflow["nodes"] == workflow["nodes"]
    assert len(replayed_assets) == len(assets)


def test_failed_input_probe_keeps_interaction_and_creates_no_product_or_compiled_asset(product_api):
    client, settings, _ = product_api
    workflow_id, interaction, references, etag = _prepare_upload_case(product_api)
    Path(settings.ffprobe_path).write_text("#!/bin/sh\nexit 1\n")
    response = client.post(
        f"/api/v2/workflows/{workflow_id}/guided/product-inputs",
        json=product_commit_request(interaction, references),
        headers={"If-Match": etag, "Idempotency-Key": "offline-product-failed-probe"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "guided_product_asset_unreadable"
    workflow, assets = _readback(client, workflow_id)
    assert workflow["nodes"] == []
    assert len(assets) == 2
    assert all(asset["source_type"] == "upload" for asset in assets)
    assert _storage_counts(settings)["asset_versions"] == 2
    runtime = create_agent_canvas_runtime(settings, bootstrap_model_policy=False)
    try:
        current = runtime.guided_interactions.get_current(workflow_id)
        assert current is not None
        assert current.interaction_id == interaction.interaction_id
        assert current.status == "open"
    finally:
        runtime.database.dispose()


def test_invalid_multiview_cardinality_does_not_materialize_product(product_api):
    client, _, _ = product_api
    workflow_id, interaction, references, etag = _prepare_upload_case(product_api)
    response = client.post(
        f"/api/v2/workflows/{workflow_id}/guided/product-inputs",
        json=product_commit_request(interaction, references[:1]),
        headers={"If-Match": etag, "Idempotency-Key": "offline-product-invalid-count"},
    )
    assert response.status_code == 422, response.text
    workflow, assets = _readback(client, workflow_id)
    assert workflow["nodes"] == []
    assert len(assets) == 2
