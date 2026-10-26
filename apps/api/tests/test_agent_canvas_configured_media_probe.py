"""The real Canvas factory honors an ffprobe executable outside PATH."""

from base64 import b64decode
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import shlex

import pytest

from app.api.v2.endpoints.agent_canvas import create_agent_canvas_runtime
from app.core.config import Settings
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_canvas import CanvasNodeV2, ProjectCreateRequestV2
from app.services.product_upload_multiview_compiler import ProductUploadMultiviewInput


pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="Executable fixtures require a POSIX shell."
)

VIDEO_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"offline fixture"
IMAGE_BYTES = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9p0AAAAASUVORK5CYII="
)


def configured_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    marker = tmp_path / "probe-called"
    executable = tmp_path / "configured-ffprobe"
    probe_json = json.dumps(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "avg_frame_rate": "24/1",
                    "duration": "5.041667",
                }
            ],
            "format": {"duration": "5.041667"},
        }
    )
    executable.write_text(
        "#!/bin/sh\n"
        f"printf 'called\\n' >> {shlex.quote(str(marker))}\n"
        f"printf '%s\\n' {shlex.quote(probe_json)}\n"
    )
    executable.chmod(0o700)
    image = tmp_path / "source.png"
    image.write_bytes(IMAGE_BYTES)
    ffmpeg = tmp_path / "configured-ffmpeg"
    ffmpeg.write_text(
        f'#!/bin/sh\nfor output; do :; done\n/bin/cp {shlex.quote(str(image))} "$output"\n'
    )
    ffmpeg.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    data = tmp_path / "media"
    (data / "v2").mkdir(parents=True)
    database = create_v2_database(data)
    try:
        upgrade_v2_schema(database)
    finally:
        database.dispose()
    return create_agent_canvas_runtime(
        Settings(
            media_data_dir=data,
            agent_runtime_mode="real",
            media_mode="real",
            ffprobe_path=str(executable),
            ffmpeg_path=str(ffmpeg),
        ),
        bootstrap_model_policy=False,
    ), marker


def test_real_factory_publishes_video_with_configured_ffprobe_outside_path(tmp_path, monkeypatch):
    runtime, marker = configured_runtime(tmp_path, monkeypatch)
    try:
        workflow = runtime.projects.create(
            ProjectCreateRequestV2(name="Offline media probe"), idempotency_key="probe-project"
        )
        now = datetime.now(timezone.utc)
        node = CanvasNodeV2(
            workflow_id=workflow.workflow_id,
            node_id="probe-video",
            node_type="video",
            creative_role="general_video",
            title="Offline video",
            generation_prompt="Saved manual prompt",
            status="draft",
            position={"x": 0, "y": 0},
            revision=1,
            created_at=now,
            updated_at=now,
        )
        runtime.workflows.add_node(node, expected_revision=workflow.revision)
        published = runtime.assets.publish_generated_bytes(
            workflow.workflow_id,
            node_id=node.node_id,
            execution_id="offline-execution",
            filename="offline-video.mp4",
            mime_type="video/mp4",
            content=VIDEO_BYTES,
            fingerprint="offline-result",
        )

        assert marker.read_text().splitlines() == ["called"]
        assert published.actual_media_facts["width"] == 1280
        assert published.actual_media_facts["height"] == 720
        assert published.actual_media_facts["duration_seconds"] == 5.041667
        assert published.actual_media_facts["frame_rate"] == 24
        assert published.actual_media_facts["has_audio"] is False
        assert published.status == "ready"
        persisted = V2AssetLibraryRepository(runtime.database).find_version(
            asset_id=published.asset_id
        )
        assert persisted is not None
        assert persisted.width == 1280
        assert persisted.duration_seconds == 5.041667
        assert runtime.assets.resolve_asset_path(published.asset_id).read_bytes() == VIDEO_BYTES
    finally:
        runtime.database.dispose()


def test_factory_product_compiler_uses_configured_ffprobe_outside_path(tmp_path, monkeypatch):
    runtime, marker = configured_runtime(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.png"
        inputs = tuple(
            ProductUploadMultiviewInput(
                asset_id=f"image-{index}",
                version_id=f"image-version-{index}",
                path=source,
                sha256=sha256(IMAGE_BYTES).hexdigest(),
                size_bytes=len(IMAGE_BYTES),
                media_type="image",
                width=1280,
                height=720,
            )
            for index in range(2)
        )
        # Exercise the factory's actual compiler; external binaries are offline fixtures.
        compiled = runtime.guided_product_inputs._compiler.compile(inputs)
        try:
            assert marker.read_text().splitlines() == ["called"] * 3
            assert compiled.output_path.read_bytes() == IMAGE_BYTES
            assert compiled.media_facts["width"] == 1280
            assert compiled.media_facts["height"] == 720
            assert compiled.ordered_inputs == ("image-version-0", "image-version-1")
        finally:
            compiled.cleanup()
    finally:
        runtime.database.dispose()
