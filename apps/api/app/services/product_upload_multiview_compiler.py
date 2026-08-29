"""Bounded FFmpeg compilation for uploaded Product Multiview images."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4

from app.services.v2_final_composition_renderer import V2MediaProbeResult
from app.tools.ffmpeg import FfmpegResult, FfmpegTool


PRODUCT_UPLOAD_MULTIVIEW_PROFILE_ID = "product-upload-multiview-v1"
PRODUCT_UPLOAD_MULTIVIEW_PROFILE_VERSION = 1
PRODUCT_UPLOAD_MULTIVIEW_MIN_INPUTS = 2
PRODUCT_UPLOAD_MULTIVIEW_MAX_INPUTS = 8
PRODUCT_UPLOAD_MULTIVIEW_COLUMNS = 2

Probe = Callable[[Path, str], V2MediaProbeResult]


class ProductUploadMultiviewCompilationError(RuntimeError):
    """A safe, stable failure from the bounded Product Multiview compiler."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ProductUploadMultiviewInput:
    """A server-resolved immutable input assertion for one uploaded image."""

    asset_id: str
    version_id: str
    path: Path
    sha256: str
    size_bytes: int
    media_type: str
    width: int
    height: int


@dataclass
class ProductUploadMultiviewCompilation:
    """A verified staged board that is ready for a later persistence owner."""

    output_path: Path
    staging_dir: Path
    output_sha256: str
    media_facts: dict[str, int | float | str | bool | None]
    ordered_inputs: tuple[str, ...]
    profile_id: str
    profile_version: int
    grid_columns: int
    grid_rows: int
    command_fingerprint: str
    compiler_fingerprint: str

    def cleanup(self) -> None:
        """Remove the staged output after publication or a caller-side abort."""

        _cleanup_staging_dir(self.staging_dir)


class ProductUploadMultiviewCompiler:
    """Compose two to eight uploaded images using one pinned FFmpeg profile."""

    def __init__(
        self,
        *,
        ffmpeg: FfmpegTool,
        probe: Probe,
        staging_root: Path,
        max_total_bytes: int,
        max_total_pixels: int,
        timeout_seconds: float,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._probe = probe
        self._staging_root = staging_root
        self._max_total_bytes = max_total_bytes
        self._max_total_pixels = max_total_pixels
        self._timeout_seconds = timeout_seconds

    def compile(
        self,
        inputs: tuple[ProductUploadMultiviewInput, ...],
    ) -> ProductUploadMultiviewCompilation:
        self._validate_count(inputs)
        self._validate_inputs(inputs)
        grid_rows = (
            len(inputs) + PRODUCT_UPLOAD_MULTIVIEW_COLUMNS - 1
        ) // PRODUCT_UPLOAD_MULTIVIEW_COLUMNS
        cell_width = max(item.width for item in inputs)
        cell_height = max(item.height for item in inputs)
        command_fingerprint = self._command_fingerprint(
            inputs,
            cell_width=cell_width,
            cell_height=cell_height,
            grid_rows=grid_rows,
        )
        staging_dir = self._staging_root / f"product-upload-multiview-{uuid4().hex}"
        output_path = staging_dir / "multiview.png"
        staging_dir.mkdir(parents=True, exist_ok=False)
        try:
            result = self._ffmpeg.compose_image_grid(
                [item.path for item in inputs],
                output_path,
                columns=PRODUCT_UPLOAD_MULTIVIEW_COLUMNS,
                rows=grid_rows,
                cell_width=cell_width,
                cell_height=cell_height,
                timeout_seconds=self._timeout_seconds,
            )
            self._validate_ffmpeg_result(result)
            facts = self._probe(output_path, "image")
            self._validate_output(output_path, facts)
            output_sha256 = _sha256(output_path)
            return ProductUploadMultiviewCompilation(
                output_path=output_path,
                staging_dir=staging_dir,
                output_sha256=output_sha256,
                media_facts=_media_facts(facts),
                ordered_inputs=tuple(item.version_id for item in inputs),
                profile_id=PRODUCT_UPLOAD_MULTIVIEW_PROFILE_ID,
                profile_version=PRODUCT_UPLOAD_MULTIVIEW_PROFILE_VERSION,
                grid_columns=PRODUCT_UPLOAD_MULTIVIEW_COLUMNS,
                grid_rows=grid_rows,
                command_fingerprint=command_fingerprint,
                compiler_fingerprint=_compiler_fingerprint(),
            )
        except ProductUploadMultiviewCompilationError:
            _cleanup_staging_dir(staging_dir)
            raise
        except OSError as exc:
            _cleanup_staging_dir(staging_dir)
            raise ProductUploadMultiviewCompilationError(
                "guided_product_multiview_compilation_failed",
                "Product Multiview compilation could not stage its output.",
            ) from exc

    def _validate_count(self, inputs: tuple[ProductUploadMultiviewInput, ...]) -> None:
        if (
            not PRODUCT_UPLOAD_MULTIVIEW_MIN_INPUTS
            <= len(inputs)
            <= PRODUCT_UPLOAD_MULTIVIEW_MAX_INPUTS
        ):
            raise ProductUploadMultiviewCompilationError(
                "guided_product_multiview_count_invalid",
                "Product Multiview requires between two and eight images.",
            )

    def _validate_inputs(self, inputs: tuple[ProductUploadMultiviewInput, ...]) -> None:
        total_bytes = 0
        total_pixels = 0
        for item in inputs:
            if item.media_type != "image":
                raise ProductUploadMultiviewCompilationError(
                    "guided_product_asset_not_image",
                    "Product Multiview inputs must be images.",
                )
            if item.width <= 0 or item.height <= 0 or item.size_bytes < 0:
                raise ProductUploadMultiviewCompilationError(
                    "guided_product_asset_unreadable",
                    "A Product Multiview input has invalid media facts.",
                )
            try:
                actual_size = item.path.stat().st_size
            except OSError as exc:
                raise ProductUploadMultiviewCompilationError(
                    "guided_product_asset_unreadable",
                    "A Product Multiview input is not readable.",
                ) from exc
            if not item.path.is_file() or actual_size != item.size_bytes:
                raise ProductUploadMultiviewCompilationError(
                    "guided_product_asset_unreadable",
                    "A Product Multiview input is not readable.",
                )
            facts = self._probe(item.path, "image")
            if facts.error or not facts.width or not facts.height:
                raise ProductUploadMultiviewCompilationError(
                    "guided_product_asset_unreadable",
                    "A Product Multiview input failed media probing.",
                )
            total_bytes += actual_size
            total_pixels += item.width * item.height
        if total_bytes > self._max_total_bytes or total_pixels > self._max_total_pixels:
            raise ProductUploadMultiviewCompilationError(
                "guided_product_multiview_compilation_failed",
                "Product Multiview inputs exceed the bounded compilation budget.",
            )

    def _validate_ffmpeg_result(self, result: FfmpegResult) -> None:
        if result.timed_out:
            raise ProductUploadMultiviewCompilationError(
                "guided_product_multiview_compilation_failed",
                "Product Multiview compilation timed out.",
            )
        if result.returncode != 0:
            message = result.stderr.lower()
            code = (
                "guided_product_ffmpeg_unavailable"
                if "no such file" in message or "not found" in message
                else "guided_product_multiview_compilation_failed"
            )
            raise ProductUploadMultiviewCompilationError(
                code,
                "Product Multiview compilation failed at the FFmpeg boundary.",
            )

    def _validate_output(self, output_path: Path, facts: V2MediaProbeResult) -> None:
        if not output_path.is_file() or output_path.stat().st_size == 0 or facts.error:
            raise ProductUploadMultiviewCompilationError(
                "guided_product_multiview_compilation_failed",
                "Product Multiview compilation produced an unreadable output.",
            )
        if not facts.width or not facts.height:
            raise ProductUploadMultiviewCompilationError(
                "guided_product_multiview_compilation_failed",
                "Product Multiview output has no readable media dimensions.",
            )

    @staticmethod
    def _command_fingerprint(
        inputs: tuple[ProductUploadMultiviewInput, ...],
        *,
        cell_width: int,
        cell_height: int,
        grid_rows: int,
    ) -> str:
        payload = {
            "profile_id": PRODUCT_UPLOAD_MULTIVIEW_PROFILE_ID,
            "profile_version": PRODUCT_UPLOAD_MULTIVIEW_PROFILE_VERSION,
            "columns": PRODUCT_UPLOAD_MULTIVIEW_COLUMNS,
            "rows": grid_rows,
            "cell_width": cell_width,
            "cell_height": cell_height,
            "inputs": [
                {
                    "version_id": item.version_id,
                    "sha256": item.sha256,
                    "width": item.width,
                    "height": item.height,
                }
                for item in inputs
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compiler_fingerprint() -> str:
    payload = f"{PRODUCT_UPLOAD_MULTIVIEW_PROFILE_ID}:{PRODUCT_UPLOAD_MULTIVIEW_PROFILE_VERSION}:scale-pad"
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _media_facts(facts: V2MediaProbeResult) -> dict[str, int | float | str | bool | None]:
    return {
        "width": facts.width,
        "height": facts.height,
        "duration_seconds": facts.duration_seconds,
        "video_codec": facts.video_codec,
        "audio_codec": facts.audio_codec,
        "has_audio": facts.has_audio,
        "sample_aspect_ratio": facts.sample_aspect_ratio,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cleanup_staging_dir(staging_dir: Path) -> None:
    shutil.rmtree(staging_dir, ignore_errors=True)
    try:
        staging_dir.parent.rmdir()
    except OSError:
        pass
