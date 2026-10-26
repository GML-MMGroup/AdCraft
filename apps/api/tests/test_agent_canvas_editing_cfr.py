"""Exercise Editing's encoded timeline with the actual local FFmpeg toolchain."""

from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.core.config import Settings
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_editing import (
    EditingBgmEntryV2,
    EditingManifestV2,
    EditingOutputSettingsV2,
    EditingVideoEntryV2,
)
from app.services.agent_canvas_composition_renderer import AgentCanvasCompositionRenderer
from app.services.agent_canvas_editing import ResolvedEditingInputs, ResolvedEditingMedia
from app.services.agent_canvas_editing_export import _fingerprint


pytestmark = [pytest.mark.integration, pytest.mark.media]


def run_tool(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture(scope="module")
def media_tools() -> tuple[str, str]:
    tools = []
    for variable, executable in (("FFMPEG_PATH", "ffmpeg"), ("FFPROBE_PATH", "ffprobe")):
        configured = os.environ.get(variable)
        resolved = shutil.which(configured or executable)
        if resolved is None:
            if configured:
                pytest.fail(f"{variable} does not identify an executable: {configured}")
            pytest.skip(f"Install {executable} or configure {variable} for real media tests.")
        tools.append(resolved)
    encoders = run_tool([tools[0], "-hide_banner", "-encoders"]).stdout
    if "libx264 " not in encoders:
        pytest.skip("These real H.264 regression tests require an FFmpeg build with libx264.")
    return tools[0], tools[1]


def create_source(ffmpeg: str, destination: Path, *, fps: int, seconds: int) -> None:
    run_tool(
        [
            ffmpeg,
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=64x64:r={fps}:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:sample_rate=48000:duration={seconds}",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ]
    )


def resolved_inputs(source: Path, *, clip_count: int) -> ResolvedEditingInputs:
    videos = []
    duration = 15 // clip_count
    for index in range(clip_count):
        asset = ProjectAssetSummaryV2(
            asset_id=f"asset_source_{index}",
            workflow_id="workflow_test",
            media_type="video",
            source_type="upload",
            display_name=f"Source {index}",
            mime_type="video/mp4",
            status="ready",
            duration_seconds=duration,
            checksum=sha256(source.read_bytes()).hexdigest(),
        )
        videos.append(
            ResolvedEditingMedia(
                asset=asset,
                path=source,
                video_entry=EditingVideoEntryV2(
                    asset_id=asset.asset_id,
                    timeline_start_seconds=index * duration,
                    trim_end_seconds=duration,
                    preserve_native_audio=clip_count == 1,
                ),
            )
        )
    return ResolvedEditingInputs(
        videos=tuple(videos),
        bgm=None,
        skipped=(),
        timeline_duration_seconds=15,
    )


def assert_cfr_media(destination: Path, ffprobe: str, *, fps: int, seconds: float) -> None:
    duration = Fraction(str(seconds))
    frame_count = duration * fps
    assert frame_count.denominator == 1, "Test timelines must end on a frame boundary."
    # count_frames decodes the stream; nb_frames alone only reads container metadata.
    inspected = run_tool(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-show_frames",
            "-show_entries",
            "frame=media_type,best_effort_timestamp",
            "-of",
            "json",
            str(destination),
        ]
    )
    assert not inspected.stderr
    metadata = json.loads(inspected.stdout)
    video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")
    assert int(video["nb_read_frames"]) == frame_count
    assert int(video["nb_frames"]) == frame_count
    assert Fraction(video["r_frame_rate"]) == fps
    assert Fraction(video["avg_frame_rate"]) == fps
    assert float(video["duration"]) == pytest.approx(seconds, abs=1e-6)
    assert float(audio["duration"]) == pytest.approx(seconds, abs=1e-6)
    assert float(metadata["format"]["duration"]) == pytest.approx(seconds, abs=1e-6)
    time_base = Fraction(video["time_base"])
    frames = [frame for frame in metadata["frames"] if frame["media_type"] == "video"]
    assert len(frames) == frame_count
    assert all(
        int(frame["best_effort_timestamp"]) * time_base == Fraction(index, fps)
        for index, frame in enumerate(frames)
    )

    packets = json.loads(
        run_tool(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_packets",
                "-show_entries",
                "packet=pts,duration",
                "-of",
                "json",
                str(destination),
            ]
        ).stdout
    )["packets"]
    assert len(packets) == frame_count
    assert all(int(packet.get("duration", 0)) > 0 for packet in packets)
    last_presented = max(packets, key=lambda packet: int(packet["pts"]))
    assert int(last_presented["duration"]) * time_base == Fraction(1, fps)
    assert (int(last_presented["pts"]) + int(last_presented["duration"])) * time_base == duration


@pytest.mark.parametrize("fps", [24, 30])
@pytest.mark.parametrize(
    "clip_count", [3, 1], ids=["three-five-second-clips", "one-fifteen-second-clip"]
)
def test_editing_export_preserves_complete_cfr_timeline(
    tmp_path: Path,
    media_tools: tuple[str, str],
    fps: int,
    clip_count: int,
) -> None:
    ffmpeg, ffprobe = media_tools
    source = tmp_path / "source.mp4"
    create_source(ffmpeg, source, fps=fps, seconds=15 // clip_count)
    renderer = AgentCanvasCompositionRenderer(
        Settings(ffmpeg_path=ffmpeg, ffprobe_path=ffprobe),
        encoder="libx264",
    )
    result = renderer.render(
        resolved_inputs(source, clip_count=clip_count),
        EditingOutputSettingsV2(resolution="64x64", fps=fps),
        staging_path=tmp_path / "editing.mp4",
    )
    assert_cfr_media(result.output_path, ffprobe, fps=fps, seconds=15)


def test_trimmed_clip_with_gaps_and_bgm_keeps_frame_aligned_timeline(
    tmp_path: Path,
    media_tools: tuple[str, str],
) -> None:
    ffmpeg, ffprobe = media_tools
    source = tmp_path / "source.mp4"
    create_source(ffmpeg, source, fps=24, seconds=2)
    original = resolved_inputs(source, clip_count=1).videos[0]
    video = ResolvedEditingMedia(
        asset=original.asset.model_copy(update={"duration_seconds": 2}),
        path=source,
        video_entry=EditingVideoEntryV2(
            asset_id=original.asset.asset_id,
            timeline_start_seconds=0.25,
            trim_start_seconds=0.5,
            trim_end_seconds=1.5,
            preserve_native_audio=True,
        ),
    )
    music_path = tmp_path / "bgm.wav"
    run_tool([ffmpeg, "-v", "error", "-i", str(source), "-vn", str(music_path)])
    music = ResolvedEditingMedia(
        asset=ProjectAssetSummaryV2(
            asset_id="asset_bgm",
            media_type="audio",
            source_type="upload",
            display_name="Synthetic BGM",
            mime_type="audio/wav",
            status="ready",
            checksum=sha256(music_path.read_bytes()).hexdigest(),
        ),
        path=music_path,
        bgm_entry=EditingBgmEntryV2(
            asset_id="asset_bgm", trim_end_seconds=1.5, fade_in_seconds=0.1, fade_out_seconds=0.1
        ),
    )
    renderer = AgentCanvasCompositionRenderer(
        Settings(ffmpeg_path=ffmpeg, ffprobe_path=ffprobe), encoder="libx264"
    )
    result = renderer.render(
        ResolvedEditingInputs(
            videos=(video,), bgm=music, skipped=(), timeline_duration_seconds=1.5
        ),
        EditingOutputSettingsV2(resolution="64x64", fps=24),
        staging_path=tmp_path / "trimmed.mp4",
    )
    assert_cfr_media(result.output_path, ffprobe, fps=24, seconds=1.5)


def test_cfr_renderer_invalidates_legacy_export_fingerprint(
    media_tools: tuple[str, str],
) -> None:
    ffmpeg, ffprobe = media_tools
    renderer = AgentCanvasCompositionRenderer(
        Settings(ffmpeg_path=ffmpeg, ffprobe_path=ffprobe),
        encoder="libx264",
    )
    # Keep the toolchain, manifest and resolved inputs unchanged: only the renderer
    # contract should prevent reuse of a completed export with a zero-duration tail.
    payload = renderer.fingerprint_payload()
    legacy_payload = {**payload, "contract": "agent-canvas-composition-renderer-v2"}
    manifest = EditingManifestV2(timeline_duration_seconds=15).model_dump(mode="json")
    inputs = ResolvedEditingInputs(videos=(), bgm=None, skipped=(), timeline_duration_seconds=15)
    current = _fingerprint(manifest, inputs, payload)
    assert current == _fingerprint(manifest, inputs, payload)
    assert current != _fingerprint(manifest, inputs, legacy_payload)
