from pathlib import Path
from dataclasses import dataclass
from typing import Any

from app.schemas.workflow_v2 import WorkflowMediaTypeV2


@dataclass(frozen=True)
class V2DetectedMediaFormat:
    detected_media_format: str
    mime_type: str
    file_extension: str
    media_type: WorkflowMediaTypeV2


class V2MediaQualityGate:
    def evaluate(
        self,
        *,
        data_dir: Path,
        file_path: Path,
        media_type: WorkflowMediaTypeV2,
        declared_mime_type: str | None = None,
    ) -> dict[str, Any]:
        absolute_path = file_path if file_path.is_absolute() else data_dir / file_path
        result: dict[str, Any] = {
            "status": "passed",
            "media_type": media_type,
            "file_path": file_path.as_posix(),
            "checks": [],
            "warnings": [
                {
                    "code": "quality_probe_unavailable",
                    "message": "Basic quality gate used file-level checks only.",
                }
            ],
        }
        if not absolute_path.exists():
            return _failed_result(
                result,
                code="asset_file_missing",
                message="Generated asset file does not exist.",
            )

        size_bytes = absolute_path.stat().st_size
        result["file_size_bytes"] = size_bytes
        if size_bytes <= 0:
            return _failed_result(
                result,
                code="quality_gate_failed",
                message="Generated asset file is empty.",
            )

        detected = detect_media_format(absolute_path)
        if detected is not None:
            result["detected_media_format"] = detected.detected_media_format
            result["mime_type"] = detected.mime_type
            result["file_extension"] = detected.file_extension
            if detected.media_type != media_type:
                return _failed_result(
                    result,
                    code="asset_mime_mismatch",
                    message=(
                        f"Detected {detected.mime_type} bytes do not match "
                        f"expected {media_type} output."
                    ),
                )
            if declared_mime_type and declared_mime_type != detected.mime_type:
                return _failed_result(
                    result,
                    code="asset_mime_mismatch",
                    message=(
                        f"Declared MIME {declared_mime_type} does not match "
                        f"detected {detected.mime_type}."
                    ),
                )

        suffix = absolute_path.suffix.lower().lstrip(".")
        if detected is not None and suffix != detected.file_extension.lstrip("."):
            return _failed_result(
                result,
                code="asset_mime_mismatch",
                message=(
                    f"Generated asset extension .{suffix or 'unknown'} does not match "
                    f"detected {detected.mime_type} bytes."
                ),
            )
        expected_suffixes = _expected_suffixes(media_type)
        if expected_suffixes and suffix not in expected_suffixes:
            return _failed_result(
                result,
                code="quality_gate_failed",
                message=(
                    f"Generated asset extension .{suffix or 'unknown'} does not match "
                    f"expected {media_type} output."
                ),
            )

        result["checks"].append(
            {
                "code": "file_non_empty",
                "status": "passed",
                "size_bytes": size_bytes,
            }
        )
        result["checks"].append(
            {
                "code": "extension_matches_media_type",
                "status": "passed",
                "suffix": suffix,
            }
        )
        return result


def detect_media_format(path: Path) -> V2DetectedMediaFormat | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
    except OSError:
        return None
    return detect_media_format_from_bytes(header)


def detect_media_format_from_bytes(data: bytes) -> V2DetectedMediaFormat | None:
    if data.startswith(b"\xff\xd8\xff"):
        return V2DetectedMediaFormat(
            detected_media_format="jpeg",
            mime_type="image/jpeg",
            file_extension=".jpg",
            media_type="image",
        )
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return V2DetectedMediaFormat(
            detected_media_format="png",
            mime_type="image/png",
            file_extension=".png",
            media_type="image",
        )
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return V2DetectedMediaFormat(
            detected_media_format="mp4",
            mime_type="video/mp4",
            file_extension=".mp4",
            media_type="video",
        )
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return V2DetectedMediaFormat(
            detected_media_format="wav",
            mime_type="audio/wav",
            file_extension=".wav",
            media_type="audio",
        )
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return V2DetectedMediaFormat(
            detected_media_format="mp3",
            mime_type="audio/mpeg",
            file_extension=".mp3",
            media_type="audio",
        )
    return None


def _failed_result(result: dict[str, Any], *, code: str, message: str) -> dict[str, Any]:
    result["status"] = "failed"
    result["error_code"] = code
    result["error_message"] = message
    result["checks"].append({"code": code, "status": "failed", "message": message})
    return result


def _expected_suffixes(media_type: WorkflowMediaTypeV2) -> set[str]:
    if media_type == "image":
        return {"png", "jpg", "jpeg", "webp"}
    if media_type == "video":
        return {"mp4", "mov", "webm", "m4v"}
    if media_type == "audio":
        return {"mp3", "wav", "m4a", "aac", "ogg"}
    return set()
