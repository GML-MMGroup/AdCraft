from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import subprocess
from typing import Literal

from app.core.config import Settings
from app.schemas.workflow_v2 import V2MediaToolchainCapabilities


PROFILE_ID = "final_composition_editor_v1"
REQUIRED_FILTERS = frozenset(
    {
        "trim",
        "atrim",
        "setpts",
        "asetpts",
        "fps",
        "scale",
        "crop",
        "pad",
        "rotate",
        "overlay",
        "format",
        "colorbalance",
        "colorlevels",
        "hue",
        "adelay",
        "afade",
        "amix",
        "volume",
        "drawtext",
        "anullsrc",
        "color",
    }
)


class V2MediaToolchainCapabilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class _ProbeKey:
    ffmpeg_path: str
    ffmpeg_mtime_ns: int | None
    ffprobe_path: str
    ffprobe_mtime_ns: int | None
    font_path: str | None
    font_mtime_ns: int | None
    configured_codec: str | None
    encoder_allowlist: tuple[str, ...]


class V2MediaToolchainCapabilityService:
    _cache: dict[_ProbeKey, V2MediaToolchainCapabilities] = {}

    def __init__(self, settings: Settings, *, runner: Runner | None = None) -> None:
        self._settings = settings
        self._runner = runner or subprocess.run

    def snapshot(self) -> V2MediaToolchainCapabilities:
        key = self._probe_key()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        snapshot = self._probe(key)
        self._cache = {key: snapshot}
        return snapshot

    def require_profile(
        self,
        profile_id: str = PROFILE_ID,
        *,
        requires_subtitles: bool = False,
    ) -> V2MediaToolchainCapabilities:
        if profile_id != PROFILE_ID:
            raise V2MediaToolchainCapabilityError(
                "v2_media_toolchain_unsupported",
                "Unknown final-composition media toolchain profile.",
            )
        snapshot = self.snapshot()
        if requires_subtitles and not snapshot.feature_flags.get("subtitles", False):
            raise V2MediaToolchainCapabilityError(
                "v2_media_toolchain_subtitle_font_missing",
                "Final composition subtitles require a readable configured server font.",
            )
        if snapshot.status == "unsupported":
            raise V2MediaToolchainCapabilityError(
                snapshot.error_code or "v2_media_toolchain_unsupported",
                "Configured FFmpeg/ffprobe does not satisfy final composition requirements.",
            )
        return snapshot

    def _probe_key(self) -> _ProbeKey:
        ffmpeg = Path(self._settings.ffmpeg_path).expanduser()
        ffprobe = Path(self._settings.ffprobe_path).expanduser()
        font = (
            Path(self._settings.final_composition_subtitle_font_path).expanduser()
            if self._settings.final_composition_subtitle_font_path
            else None
        )
        return _ProbeKey(
            ffmpeg_path=str(ffmpeg),
            ffmpeg_mtime_ns=_mtime_ns(ffmpeg),
            ffprobe_path=str(ffprobe),
            ffprobe_mtime_ns=_mtime_ns(ffprobe),
            font_path=str(font) if font else None,
            font_mtime_ns=_mtime_ns(font) if font else None,
            configured_codec=self._settings.ffmpeg_video_codec,
            encoder_allowlist=_encoder_allowlist(self._settings.ffmpeg_allowed_video_encoders),
        )

    def _probe(self, key: _ProbeKey) -> V2MediaToolchainCapabilities:
        errors: list[str] = []
        ffmpeg_version_output = self._command([key.ffmpeg_path, "-version"], errors, "ffmpeg")
        ffprobe_version_output = self._command([key.ffprobe_path, "-version"], errors, "ffprobe")
        filters_output = self._command(
            [key.ffmpeg_path, "-hide_banner", "-filters"], errors, "ffmpeg filters"
        )
        encoders_output = self._command(
            [key.ffmpeg_path, "-hide_banner", "-encoders"], errors, "ffmpeg encoders"
        )
        ffmpeg_version = _version(ffmpeg_version_output, "ffmpeg")
        ffprobe_version = _version(ffprobe_version_output, "ffprobe")
        filters = _names(filters_output)
        encoders = _names(encoders_output)
        missing = [f"filter:{name}" for name in sorted(REQUIRED_FILTERS - filters)]
        allowlist = key.encoder_allowlist
        selected_encoder = _select_encoder(
            configured_codec=key.configured_codec,
            allowlist=allowlist,
            encoders=encoders,
        )
        if selected_encoder is None:
            missing.append("video_encoder:h264")
        if "aac" not in encoders:
            missing.append("audio_encoder:aac")
        if not _supported_version(ffmpeg_version) or not _supported_version(ffprobe_version):
            missing.append("version:>=6.1,<8")
        if not _same_version_family(ffmpeg_version, ffprobe_version):
            missing.append("tool_pair:version_family")
        font_readable = bool(key.font_path and Path(key.font_path).is_file())
        feature_flags = {
            "subtitles": font_readable and "drawtext" in filters,
            "source_audio": {"atrim", "amix", "adelay"}.issubset(filters),
            "visual_composition": {"overlay", "colorbalance", "colorlevels", "hue"}.issubset(
                filters
            ),
        }
        degraded: list[str] = []
        if selected_encoder == "libopenh264":
            degraded.append("libx264_to_libopenh264")
        if not font_readable:
            degraded.append("subtitle_font_unavailable")
        executable_missing = bool(errors)
        status: Literal["ready", "degraded", "unsupported"]
        if missing or executable_missing:
            status = "unsupported"
        elif degraded:
            status = "degraded"
        else:
            status = "ready"
        error_code = None
        if executable_missing:
            error_code = "v2_media_toolchain_unavailable"
        elif missing:
            error_code = "v2_media_toolchain_unsupported"
        return V2MediaToolchainCapabilities(
            status=status,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            ffmpeg_fingerprint=_fingerprint(key.ffmpeg_path, key.ffmpeg_mtime_ns),
            ffprobe_fingerprint=_fingerprint(key.ffprobe_path, key.ffprobe_mtime_ns),
            selected_video_encoder=selected_encoder,
            audio_encoder="aac" if "aac" in encoders else None,
            feature_flags=feature_flags,
            missing_requirements=missing,
            degraded_fallbacks=degraded,
            error_code=error_code,
        )

    def _command(self, args: list[str], errors: list[str], label: str) -> str:
        try:
            completed = self._runner(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._settings.ffmpeg_capability_timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            errors.append(f"{label}:{type(exc).__name__}")
            return ""
        if completed.returncode != 0:
            errors.append(f"{label}:exit_{completed.returncode}")
            return ""
        return completed.stdout or ""


def _mtime_ns(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _encoder_allowlist(value: str) -> tuple[str, ...]:
    return tuple(candidate.strip() for candidate in value.split(",") if candidate.strip())


def _version(output: str, executable: str) -> str | None:
    match = re.search(
        rf"{re.escape(executable)} version n?([0-9]+(?:\.[0-9]+){{0,2}})",
        output,
    )
    return match.group(1) if match else None


def _names(output: str) -> set[str]:
    return set(re.findall(r"^\s*[\.A-Z]{2,7}\s+([a-zA-Z0-9_]+)\b", output, re.MULTILINE))


def _supported_version(value: str | None) -> bool:
    if value is None:
        return False
    parts = tuple(int(part) for part in value.split("."))
    return (6, 1) <= parts < (8,)


def _same_version_family(first: str | None, second: str | None) -> bool:
    if first is None or second is None:
        return False
    return first.split(".", maxsplit=1)[0] == second.split(".", maxsplit=1)[0]


def _select_encoder(
    *,
    configured_codec: str | None,
    allowlist: tuple[str, ...],
    encoders: set[str],
) -> str | None:
    candidates = [configured_codec, "libx264", "libopenh264", *allowlist]
    for candidate in candidates:
        if candidate and candidate in allowlist and candidate in encoders:
            return candidate
    return None


def _fingerprint(path: str, mtime_ns: int | None) -> str:
    digest = hashlib.sha256(f"{path}|{mtime_ns}".encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"
