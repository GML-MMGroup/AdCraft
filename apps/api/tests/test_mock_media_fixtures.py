from pathlib import Path

import pytest

from app.tools.mock_media_fixtures import (
    MockMediaFixtureError,
    deterministic_mock_media_bytes,
)


def test_deterministic_mock_media_bytes_returns_png_for_image(tmp_path: Path) -> None:
    content = deterministic_mock_media_bytes("image", data_dir=tmp_path, ffmpeg_path="ffmpeg")

    assert content.startswith(b"\x89PNG\r\n\x1a\n")


def test_deterministic_mock_media_bytes_rejects_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(MockMediaFixtureError):
        deterministic_mock_media_bytes("unknown", data_dir=tmp_path, ffmpeg_path="ffmpeg")
