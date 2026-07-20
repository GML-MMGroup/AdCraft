from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import socket
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

from app.core.config import Settings
from app.tools.media_provider_protocol import MediaConfigurationError
from app.tools.seedance_adapter import (
    DEFAULT_VIDEO_RATIO,
    VolcengineSeedanceAdapter,
    _final_video_segments,
    _normalize_image_generation_size,
    _normalize_video_ratio,
    _normalize_video_resolution,
    _video_generation_task_url,
)
from app.tools.media_response_parsing import (
    _image_base64_from_response,
    _image_url_from_response,
    _media_api_error,
    _optional_video_generation_task_id_from_response,
    _video_duration_from_response,
    _video_generation_task_id_from_response,
    _video_url_from_response,
)
from app.tools.media_asset_builders import (
    _assets_for_product,
    _assets_for_storyboard_scene,
    _character_specs,
    _character_turnaround_asset,
    _character_turnaround_prompt,
    _image_generation_reference_inputs,
    _product_image_asset,
    _product_image_prompt,
    _product_item_context,
    _product_specs,
    _real_audio_asset,
    _scene_reference_asset,
    _scene_reference_prompt,
    _scene_specs,
    _storyboard_image_asset,
    _storyboard_image_prompt,
    _storyboard_item_context,
    _storyboard_video_segment_asset,
    _url,
)
from app.tools.media_artifact_io import (
    _write_base64_asset,
    _write_character_metadata,
    _write_json_metadata,
)
from app.tools.legacy_bgm_adapter import LegacyBgmAdapter
from app.tools.media_subtitles import generate_subtitle_asset
from app.tools.volcengine_image_generations import (
    serialize_volcengine_image_generation_request,
)
from app.tools.media_composition import (
    _composed_video_url,
    _segments_are_downloaded,
    compose_downloaded_video_segments,
)


def _v2_sanitized_reference_assets(
    reference_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            key: reference[key]
            for key in (
                "asset_id",
                "version_id",
                "slot_id",
                "role",
                "semantic_type",
                "media_type",
                "mime_type",
                "provider_input_type",
                "model_input_type",
                "source",
                "delivery_status",
                "byte_count",
            )
            if reference.get(key) is not None
        }
        for reference in reference_assets
    ]


class _ProviderDownloadError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        http_status: int | None = None,
        expected_bytes: int | None = None,
        received_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status
        self.expected_bytes = expected_bytes
        self.received_bytes = received_bytes


def _is_v2_provider_result_path(relative_path: Path) -> bool:
    parts = relative_path.parts
    return (
        len(parts) == 6
        and parts[0] == "assets"
        and parts[1] == "generated-provider"
        and parts[3] == "provider-task-results"
        and parts[5] == "output-0.mp4"
    )


def _validate_v2_provider_result_output_path(data_dir: Path, output_path: Path) -> None:
    try:
        relative_path = output_path.resolve(strict=False).relative_to(data_dir.resolve())
    except ValueError as exc:
        raise ValueError(
            "V2 provider result output must stay inside the media data directory."
        ) from exc
    if not _is_v2_provider_result_path(relative_path):
        raise ValueError("V2 provider result output must use the canonical staging path.")


def _is_video_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return False
    return len(header) >= 12 and header[4:8] == b"ftyp"


def _content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    raw_value = headers.get("Content-Length") if hasattr(headers, "get") else None
    try:
        return int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        return None


def _with_download_bytes(
    exc: Exception,
    expected_bytes: int | None,
    received_bytes: int,
) -> _ProviderDownloadError:
    if isinstance(exc, _ProviderDownloadError):
        if exc.expected_bytes is None:
            exc.expected_bytes = expected_bytes
        if exc.received_bytes is None:
            exc.received_bytes = received_bytes
        return exc
    if isinstance(exc, urllib_error.HTTPError):
        status = exc.code
        if status == 408:
            return _ProviderDownloadError(
                "provider_download_http_408",
                "Remote media download timed out.",
                retryable=True,
                http_status=status,
                expected_bytes=expected_bytes,
                received_bytes=received_bytes,
            )
        if status == 429:
            return _ProviderDownloadError(
                "provider_download_http_429",
                "Remote media download was rate limited.",
                retryable=True,
                http_status=status,
                expected_bytes=expected_bytes,
                received_bytes=received_bytes,
            )
        if 500 <= status <= 599:
            return _ProviderDownloadError(
                "provider_download_http_5xx",
                "Remote media download service is temporarily unavailable.",
                retryable=True,
                http_status=status,
                expected_bytes=expected_bytes,
                received_bytes=received_bytes,
            )
        if status in {401, 403}:
            return _ProviderDownloadError(
                f"provider_download_http_{status}",
                "Remote media download authorization failed.",
                retryable=False,
                http_status=status,
                expected_bytes=expected_bytes,
                received_bytes=received_bytes,
            )
        if status == 404:
            return _ProviderDownloadError(
                "provider_result_unavailable",
                "Remote provider result is unavailable.",
                retryable=False,
                http_status=status,
                expected_bytes=expected_bytes,
                received_bytes=received_bytes,
            )
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return _ProviderDownloadError(
            "provider_download_timeout",
            "Remote media download timed out.",
            retryable=True,
            expected_bytes=expected_bytes,
            received_bytes=received_bytes,
        )
    if isinstance(exc, urllib_error.URLError) and isinstance(
        getattr(exc, "reason", None), (TimeoutError, socket.timeout)
    ):
        return _ProviderDownloadError(
            "provider_download_timeout",
            "Remote media download timed out.",
            retryable=True,
            expected_bytes=expected_bytes,
            received_bytes=received_bytes,
        )
    return _ProviderDownloadError(
        "provider_download_connection_error",
        "Remote media download connection failed.",
        retryable=True,
        expected_bytes=expected_bytes,
        received_bytes=received_bytes,
    )


def _provider_download_failure(exc: Exception) -> dict[str, Any]:
    classified = _with_download_bytes(exc, None, 0)
    return {
        "local_path": None,
        "download_status": "failed",
        "download_error_code": classified.code,
        "download_error": str(classified),
        "download_retryable": classified.retryable,
        "download_http_status": classified.http_status,
        "download_expected_bytes": classified.expected_bytes,
        "download_received_bytes": classified.received_bytes,
    }


class RealMediaProvider:
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._validate_settings()

    def _validate_settings(self) -> None:
        required_values = [
            ("VIDEO_GENERATION_API_KEY", self._settings.video_generation_api_key),
            ("VIDEO_GENERATION_ENDPOINT", self._settings.video_generation_endpoint),
            ("IMAGE_GENERATION_API_KEY", self._settings.image_generation_api_key),
            ("IMAGE_GENERATION_ENDPOINT", self._settings.image_generation_endpoint),
        ]
        if not self._settings.skip_audio_agents:
            required_values.extend(
                [
                    ("SOUND_EFFECTS_API_KEY", self._settings.sound_effects_api_key),
                    ("SOUND_EFFECTS_ENDPOINT", self._settings.sound_effects_endpoint),
                    ("TTS_API_KEY", self._settings.tts_api_key),
                    ("TTS_ENDPOINT", self._settings.tts_endpoint),
                    ("BGM_API_KEY", self._settings.bgm_api_key),
                    ("BGM_ENDPOINT", self._settings.bgm_endpoint),
                ]
            )
        for name, value in required_values:
            if not value:
                raise MediaConfigurationError(f"Real media mode is enabled, but {name} is missing.")

        if (
            self._settings.composition_provider != "ffmpeg"
            and not self._settings.composition_endpoint
        ):
            raise MediaConfigurationError(
                "Real media mode is enabled, but COMPOSITION_ENDPOINT is missing."
            )

        _normalize_image_generation_size(self._settings.image_generation_size)

    # V1-only compatibility adapter; V2 image generation uses generate_v2_canonical_image.
    def generate_storyboard_images(
        self,
        storyboard_scenes: list[dict[str, Any]],
        workflow_id: str,
        input_assets: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        input_assets = input_assets or []
        assets = []
        for scene in storyboard_scenes:
            order = int(scene["order"])
            prompt = _storyboard_image_prompt(scene)
            scene_input_assets = _assets_for_storyboard_scene(scene, input_assets)
            response = self._submit_image_generation_request(
                {
                    "model": self._settings.image_generation_model,
                    "prompt": prompt,
                    "response_format": "url",
                    "size": _normalize_image_generation_size(self._settings.image_generation_size),
                    "watermark": False,
                    "references": _image_generation_reference_inputs(scene_input_assets),
                    "context": _storyboard_item_context(scene, context or {}),
                }
            )
            image_url = _image_url_from_response(response)
            image_base64 = _image_base64_from_response(response)
            if image_url is None and image_base64 is None:
                raise ValueError(
                    "Storyboard image generation failed: response did not include "
                    "image url or base64 data."
                )

            relative_image_path = Path("storyboards") / workflow_id / f"scene-{order}.png"
            download_result: dict[str, Any]
            if image_url:
                download_result = self._download_remote_asset(image_url, relative_image_path)
                if download_result.get("download_status") == "failed":
                    raise ValueError(
                        "Storyboard image download failed: "
                        f"scene={order}, url={image_url}, "
                        f"error={download_result.get('download_error')}"
                    )
            else:
                download_result = _write_base64_asset(
                    self._settings.media_data_dir,
                    image_base64 or "",
                    relative_image_path,
                )

            asset = _storyboard_image_asset(
                scene=scene,
                workflow_id=workflow_id,
                prompt=prompt,
                provider="volcengine-storyboard-image-generation",
                model=self._settings.image_generation_model,
                response=response,
                remote_url=image_url,
                download_result=download_result,
                input_assets=scene_input_assets,
            )
            _write_json_metadata(self._settings.media_data_dir, asset["metadata_path"], asset)
            assets.append(asset)
        return {
            "provider": "volcengine-storyboard-image-generation",
            "model": self._settings.image_generation_model,
            "assets": assets,
            "input_assets": input_assets,
            "output_assets": assets,
        }

    # V1-only compatibility adapter; V2 image generation uses generate_v2_canonical_image.
    def generate_scene_reference_images(
        self,
        scene_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        assets = []
        for index, scene in enumerate(_scene_specs(scene_design), start=1):
            prompt = _scene_reference_prompt(scene)
            response = self._submit_image_generation_request(
                {
                    "model": self._settings.image_generation_model,
                    "prompt": prompt,
                    "response_format": "url",
                    "size": _normalize_image_generation_size(self._settings.image_generation_size),
                    "watermark": False,
                }
            )
            image_url = _image_url_from_response(response)
            image_base64 = _image_base64_from_response(response)
            if image_url is None and image_base64 is None:
                raise ValueError(
                    "Scene reference generation failed: response did not include image url or base64 data."
                )
            relative_image_path = Path("scenes") / workflow_id / f"scene-{index}.png"
            if image_url:
                download_result = self._download_remote_asset(image_url, relative_image_path)
                if download_result.get("download_status") == "failed":
                    raise ValueError(
                        "Scene reference image download failed: "
                        f"scene={index}, url={image_url}, error={download_result.get('download_error')}"
                    )
            else:
                download_result = _write_base64_asset(
                    self._settings.media_data_dir,
                    image_base64 or "",
                    relative_image_path,
                )
            asset = _scene_reference_asset(
                workflow_id=workflow_id,
                index=index,
                scene=scene,
                prompt=prompt,
                provider="volcengine-scene-reference-generation",
                model=self._settings.image_generation_model,
                response=response,
                remote_url=image_url,
                download_result=download_result,
            )
            _write_json_metadata(self._settings.media_data_dir, asset["metadata_path"], asset)
            assets.append(asset)
        return {
            "provider": "volcengine-scene-reference-generation",
            "model": self._settings.image_generation_model,
            "assets": assets,
            "output_assets": assets,
        }

    def generate_product_images(
        self,
        product_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        input_assets = [
            asset for asset in product_design.get("reference_assets", []) if isinstance(asset, dict)
        ]
        assets = []
        for index, product in enumerate(_product_specs(product_design), start=1):
            prompt = _product_image_prompt(product)
            product_input_assets = _assets_for_product(product, input_assets)
            if (
                product.get("reference_mode") == "strict"
                and product.get("input_asset_ids")
                and not product_input_assets
            ):
                raise ValueError("product_reference_dropped")
            response = self._submit_image_generation_request(
                {
                    "model": self._settings.image_generation_model,
                    "prompt": prompt,
                    "response_format": "url",
                    "size": _normalize_image_generation_size(self._settings.image_generation_size),
                    "watermark": False,
                    "references": _image_generation_reference_inputs(product_input_assets),
                    "context": _product_item_context(product, product_input_assets),
                }
            )
            image_url = _image_url_from_response(response)
            image_base64 = _image_base64_from_response(response)
            if image_url is None and image_base64 is None:
                raise ValueError(
                    "Product image generation failed: response did not include "
                    "image url or base64 data."
                )
            relative_image_path = Path("products") / workflow_id / f"product-{index}.png"
            if image_url:
                download_result = self._download_remote_asset(image_url, relative_image_path)
                if download_result.get("download_status") == "failed":
                    raise ValueError(
                        "Product image download failed: "
                        f"product={index}, url={image_url}, "
                        f"error={download_result.get('download_error')}"
                    )
            else:
                download_result = _write_base64_asset(
                    self._settings.media_data_dir,
                    image_base64 or "",
                    relative_image_path,
                )
            asset = _product_image_asset(
                workflow_id=workflow_id,
                index=index,
                product=product,
                prompt=prompt,
                provider="volcengine-product-image-generation",
                model=self._settings.image_generation_model,
                response=response,
                remote_url=image_url,
                download_result=download_result,
                input_assets=product_input_assets,
            )
            _write_json_metadata(self._settings.media_data_dir, asset["metadata_path"], asset)
            assets.append(asset)
        return {
            "provider": "volcengine-product-image-generation",
            "model": self._settings.image_generation_model,
            "assets": assets,
            "input_assets": input_assets,
            "output_assets": assets,
        }

    def generate_v2_canonical_image(
        self,
        request: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        prompt = str(request.get("prompt") or "")
        slot_type = str(request.get("slot_type") or "image")
        slot_id = str(request.get("slot_id") or slot_type).replace(":", "_")
        semantic_type = str(request.get("semantic_type") or slot_type)
        reference_assets = [
            asset for asset in request.get("reference_assets", []) if isinstance(asset, dict)
        ]
        body, wire_audit = serialize_volcengine_image_generation_request(
            model=self._settings.image_generation_model,
            canonical_prompt=prompt,
            size=_normalize_image_generation_size(self._settings.image_generation_size),
            references=reference_assets,
            required_reference_asset_ids=list(request.get("submitted_reference_asset_ids") or []),
            response_format="url",
            watermark=False,
        )
        submitted_wire_audit = wire_audit.model_copy(
            update={
                "submitted_reference_asset_ids": list(wire_audit.serialized_reference_asset_ids)
            }
        ).model_dump(mode="json")
        response = self._submit_image_generation_request(body)
        image_url = _image_url_from_response(response)
        image_base64 = _image_base64_from_response(response)
        if image_url is None and image_base64 is None:
            raise ValueError(
                "V2 canonical image generation failed: response did not include image url or base64 data."
            )
        relative_image_path = Path("assets") / "generated-provider" / workflow_id / f"{slot_id}.png"
        if image_url:
            download_result = self._download_remote_asset(image_url, relative_image_path)
            if download_result.get("download_status") == "failed":
                raise ValueError(
                    "V2 canonical image download failed: "
                    f"slot_id={request.get('slot_id')}, url={image_url}, "
                    f"error={download_result.get('download_error')}"
                )
        else:
            download_result = _write_base64_asset(
                self._settings.media_data_dir,
                image_base64 or "",
                relative_image_path,
            )
        asset = {
            "provider": request.get("provider") or "volcengine-v2-canonical-image-generation",
            "model": self._settings.image_generation_model,
            "asset_id": f"{slot_id}-v2-canonical-image",
            "asset_type": "image",
            "type": "image",
            "media_type": "image",
            "kind": "image",
            "role": semantic_type,
            "semantic_type": semantic_type,
            "entity_id": request.get("item_id"),
            "item_id": request.get("item_id"),
            "slot_id": request.get("slot_id"),
            "slot_type": slot_type,
            "prompt": prompt,
            "url": image_url,
            "remote_url": image_url,
            "local_path": download_result.get("local_path"),
            "mime_type": "image/png",
            "status": response.get("status", "ready"),
            "download_status": download_result.get("download_status"),
            "download_error": download_result.get("download_error"),
            "input_asset_ids": list(request.get("submitted_reference_asset_ids") or []),
            "input_assets": _v2_sanitized_reference_assets(reference_assets),
            "prompt_audit": request.get("prompt_audit"),
            "reference_wire_audit": submitted_wire_audit,
            "provider_payload": {
                "provider_prompt": prompt,
                "reference_asset_ids": list(request.get("submitted_reference_asset_ids") or []),
                "reference_wire_audit": submitted_wire_audit,
            },
            "raw_response": response,
        }
        return {
            "provider": asset["provider"],
            "model": self._settings.image_generation_model,
            "assets": [asset],
            "input_assets": _v2_sanitized_reference_assets(reference_assets),
            "output_assets": [asset],
        }

    def generate_storyboard_video(
        self,
        storyboard_video_prompt: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        adapter = VolcengineSeedanceAdapter(self._settings)
        resolution = _normalize_video_resolution(
            storyboard_video_prompt.get("output_resolution")
            or storyboard_video_prompt.get("resolution")
            or self._settings.video_generation_resolution
        )
        ratio = _normalize_video_ratio(
            storyboard_video_prompt.get("aspect_ratio")
            or storyboard_video_prompt.get("ratio")
            or DEFAULT_VIDEO_RATIO
        )
        segments = [
            {
                **segment,
                "resolution": resolution,
                "ratio": ratio,
            }
            for segment in _final_video_segments(storyboard_video_prompt)
        ]
        submitted_segments: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(3, max(len(segments), 1))) as executor:
            futures = [
                executor.submit(
                    self._submit_storyboard_video_segment,
                    segment,
                    adapter,
                    workflow_id,
                    resolution,
                    ratio,
                )
                for segment in segments
            ]
            for future in as_completed(futures):
                submitted_segments.append(future.result())

        submitted_segments.sort(key=lambda segment: int(segment["order"]))
        return {
            "provider": "volcengine-storyboard-video-generation",
            "model": self._settings.video_generation_model,
            "asset_id": "storyboard-video-generation",
            "segments": submitted_segments,
            "input_assets": storyboard_video_prompt.get("input_assets", []),
            "duration_seconds": storyboard_video_prompt.get("duration_seconds"),
            "resolution": resolution,
            "ratio": ratio,
            "mime_type": "video/mp4",
            "composition_status": "ready"
            if _segments_are_downloaded(submitted_segments)
            else "waiting_for_segments",
            "status": "submitted",
        }

    def _submit_storyboard_video_segment(
        self,
        segment: dict[str, Any],
        adapter: VolcengineSeedanceAdapter,
        workflow_id: str,
        resolution: str,
        ratio: str,
    ) -> dict[str, Any]:
        response = self.submit_seedance_segment_task(segment, adapter, ratio, resolution)
        task_id = _video_generation_task_id_from_response(response)
        video_url = _video_url_from_response(response)
        relative_video_path = (
            Path("videos") / workflow_id / "segments" / (f"segment-{segment['order']}.mp4")
        )
        download_result = self._download_remote_asset(video_url, relative_video_path)
        segment_asset = _storyboard_video_segment_asset(
            segment=segment,
            workflow_id=workflow_id,
            provider="volcengine-seedance-storyboard-segment",
            model=self._settings.video_generation_model,
            task_id=task_id,
            task_query_url=adapter.task_url(task_id),
            response=response,
            remote_url=video_url,
            resolution=resolution,
            ratio=ratio,
            download_result=download_result,
        )
        _write_json_metadata(
            self._settings.media_data_dir,
            segment_asset["metadata_path"],
            segment_asset,
        )
        return segment_asset

    # V1-only compatibility adapter; V2 image generation uses generate_v2_canonical_image.
    def generate_character_turnaround_images(
        self,
        character_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        assets = []
        for index, character in enumerate(_character_specs(character_design), start=1):
            prompt = _character_turnaround_prompt(character)
            response = self._submit_image_generation_request(
                {
                    "model": self._settings.image_generation_model,
                    "prompt": prompt,
                    "response_format": "url",
                    "size": _normalize_image_generation_size(self._settings.image_generation_size),
                    "watermark": False,
                }
            )
            image_url = _image_url_from_response(response)
            image_base64 = _image_base64_from_response(response)
            if image_url is None and image_base64 is None:
                raise ValueError(
                    "Character turnaround generation failed: response did not include "
                    "image url or base64 data."
                )
            asset = _character_turnaround_asset(
                workflow_id=workflow_id,
                index=index,
                character=character,
                prompt=prompt,
                provider="volcengine-character-turnaround-generation",
                model=self._settings.image_generation_model,
                url=image_url,
                status=response.get("status", "ready"),
            )
            local_image_path = (
                Path("characters") / workflow_id / asset["character_id"] / ("turnaround.png")
            )
            if image_url:
                asset.update(self._download_remote_asset(image_url, local_image_path))
            elif image_base64:
                asset.update(
                    _write_base64_asset(
                        self._settings.media_data_dir,
                        image_base64,
                        local_image_path,
                    )
                )
            _write_character_metadata(self._settings.media_data_dir, asset)
            assets.append(asset)
        return {
            "provider": "volcengine-character-turnaround-generation",
            "model": self._settings.image_generation_model,
            "assets": assets,
        }

    def _submit_image_generation_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = self._settings.image_generation_endpoint or ""
        request = urllib_request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self._settings.image_generation_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=120) as response:
                response_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            raise _media_api_error(
                exc=exc,
                endpoint=endpoint,
                payload=payload,
            ) from exc
        return json.loads(response_body) if response_body else {}

    def _download_remote_file(self, url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib_request.urlopen(url, timeout=120) as response:
            output_path.write_bytes(response.read())

    def _download_remote_asset(
        self,
        url: str | None,
        relative_path: Path,
    ) -> dict[str, Any]:
        if not url:
            return {
                "local_path": None,
                "download_status": "waiting_for_remote_url",
            }

        output_path = self._settings.media_data_dir / relative_path
        v2_result_path = _is_v2_provider_result_path(relative_path)
        try:
            if v2_result_path:
                self._download_v2_provider_result(url, output_path)
            else:
                self._download_remote_file(url, output_path)
        except Exception as exc:  # noqa: BLE001 - convert transport errors at this boundary.
            if v2_result_path:
                return _provider_download_failure(exc)
            if output_path.exists():
                output_path.unlink()
            return {
                "local_path": None,
                "download_status": "failed",
                "download_error": str(exc),
            }

        return {
            "local_path": relative_path.as_posix(),
            "download_status": "downloaded",
        }

    def _download_v2_provider_result(self, url: str, output_path: Path) -> None:
        _validate_v2_provider_result_output_path(self._settings.media_data_dir, output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            if output_path.stat().st_size > 0 and _is_video_file(output_path):
                return
            output_path.unlink()
        part_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.part")
        received_bytes = 0
        expected_bytes: int | None = None
        started_at = time.monotonic()
        try:
            with urllib_request.urlopen(url, timeout=120) as response:
                expected_bytes = _content_length(response)
                with part_path.open("wb") as handle:
                    while True:
                        if time.monotonic() - started_at >= 120:
                            raise TimeoutError("Remote media download timed out.")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received_bytes += len(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            if expected_bytes is not None and received_bytes != expected_bytes:
                raise _ProviderDownloadError(
                    "provider_download_incomplete",
                    "Downloaded provider media did not match Content-Length.",
                    retryable=True,
                    expected_bytes=expected_bytes,
                    received_bytes=received_bytes,
                )
            if received_bytes <= 0 or not _is_video_file(part_path):
                raise _ProviderDownloadError(
                    "provider_download_invalid_media",
                    "Downloaded provider media is not a valid video output.",
                    retryable=False,
                    expected_bytes=expected_bytes,
                    received_bytes=received_bytes,
                )
            part_path.replace(output_path)
        except Exception as exc:
            if part_path.exists():
                part_path.unlink()
            raise _with_download_bytes(exc, expected_bytes, received_bytes) from exc

    def generate_subtitle_asset(
        self,
        script: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_subtitle_asset(
            script,
            duration_seconds,
            workflow_id,
            self._settings.media_data_dir,
        )

    def generate_audio_assets(
        self,
        sound_effects_plan: dict[str, Any],
        voiceover_plan: dict[str, Any],
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        sound_effects_asset = _real_audio_asset(
            self._settings.sound_effects_endpoint or "",
            workflow_id,
            "sound-effects",
            self._settings.sound_effects_model,
            sound_effects_plan,
        )
        voiceover_asset = _real_audio_asset(
            self._settings.tts_endpoint or "",
            workflow_id,
            "voiceover",
            self._settings.tts_model,
            voiceover_plan,
        )
        bgm_asset = _real_audio_asset(
            self._settings.bgm_endpoint or "",
            workflow_id,
            "bgm",
            self._settings.bgm_model or "",
            bgm_plan,
        )
        return {
            "provider": "volcengine-audio-generation",
            "asset_id": "audio-package",
            "source_assets": {
                "sound-effects": sound_effects_asset["asset_id"],
                "voiceover": voiceover_asset["asset_id"],
                "bgm": bgm_asset["asset_id"],
            },
            "assets": [sound_effects_asset, voiceover_asset, bgm_asset],
            "status": "submitted",
        }

    def generate_bgm_audio(
        self,
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        adapter = LegacyBgmAdapter(
            self._settings,
            self._settings.media_data_dir,
        )
        asset = adapter.generate_bgm_audio(bgm_plan, workflow_id)
        return {
            "provider": "volcengine_ai_music",
            "model": self._settings.bgm_model,
            "asset_id": "bgm-audio",
            "assets": [asset],
            "output_assets": [asset],
            "status": asset.get("status", "submitted"),
        }

    def retrieve_bgm_audio_task(
        self,
        task_id: str,
        *,
        workflow_id: str,
        provider_payload: dict[str, Any],
        download_media: bool = True,
    ) -> dict[str, Any]:
        adapter = LegacyBgmAdapter(
            self._settings,
            self._settings.media_data_dir,
        )
        return adapter.retrieve_bgm_audio_task(
            task_id,
            workflow_id=workflow_id,
            provider_payload=provider_payload,
            download_media=download_media,
        )

    def synchronize_audio_video(
        self,
        video_asset: dict[str, Any],
        audio_asset: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        endpoint = (
            self._settings.composition_endpoint or self._settings.video_generation_endpoint or ""
        )
        return {
            "provider": "volcengine-timeline-sync",
            "asset_id": "synchronized-preview-video",
            "video_asset": video_asset["asset_id"],
            "audio_asset": audio_asset["asset_id"],
            "url": _url(endpoint, workflow_id, "videos/synchronized-preview-video.mp4"),
            "mime_type": "video/mp4",
            "status": "submitted",
        }

    def generate_final_video_from_multimodal_prompt(
        self,
        final_video_prompt: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        adapter = VolcengineSeedanceAdapter(self._settings)
        source_assets = [
            asset["asset_id"]
            for asset in final_video_prompt.get("input_assets", [])
            if asset.get("asset_id")
        ]
        segments = self.generate_final_video_segments(final_video_prompt)
        submitted_segments = []
        for segment in segments:
            response = self.submit_seedance_segment_task(
                segment,
                adapter,
                str(final_video_prompt.get("aspect_ratio") or DEFAULT_VIDEO_RATIO),
            )
            task_id = _video_generation_task_id_from_response(response)
            video_url = _video_url_from_response(response)
            download_result = self._download_remote_asset(
                video_url,
                Path("final") / workflow_id / f"segment-{segment['order']}.mp4",
            )
            submitted_segments.append(
                {
                    **segment,
                    "provider": "volcengine-seedance-segment-generation",
                    "task_id": task_id,
                    "task_query_url": adapter.task_url(task_id),
                    "status": response.get("status", "submitted"),
                    "url": video_url,
                    "remote_url": video_url,
                    "mime_type": "video/mp4",
                    **download_result,
                    "raw_response": response,
                }
            )
        return {
            "provider": "volcengine-final-video-generation",
            "model": self._settings.video_generation_model,
            "asset_id": "final-video-generation",
            "source_assets": source_assets,
            "duration_seconds": final_video_prompt.get("duration_seconds"),
            "segments": submitted_segments,
            "task_ids": [segment["task_id"] for segment in submitted_segments],
            "task_query_urls": [segment["task_query_url"] for segment in submitted_segments],
            "url": _composed_video_url(submitted_segments),
            "local_path": None,
            "mime_type": "video/mp4",
            "composition_status": "ready"
            if _composed_video_url(submitted_segments)
            else "waiting_for_segments",
            "status": "submitted",
        }

    def generate_final_video_segments(
        self,
        final_video_prompt: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return _final_video_segments(final_video_prompt)

    def submit_seedance_segment_task(
        self,
        segment: dict[str, Any],
        adapter: VolcengineSeedanceAdapter,
        ratio: str,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        return self._submit_video_generation_request(
            adapter.payload_for_segment(segment, ratio=ratio, resolution=resolution)
        )

    def _submit_video_generation_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = self._settings.video_generation_endpoint or ""
        request = urllib_request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self._settings.video_generation_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=120) as response:
                response_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            raise _media_api_error(
                exc=exc,
                endpoint=endpoint,
                payload=payload,
            ) from exc
        return json.loads(response_body) if response_body else {}

    def retrieve_seedance_task(
        self,
        task_id: str,
        workflow_id: str | None = None,
        segment_order: int | None = None,
    ) -> dict[str, Any]:
        task_url = _video_generation_task_url(
            self._settings.video_generation_endpoint or "",
            task_id,
        )
        response = self._get_video_generation_task_response(task_url)
        response_task_id = _video_generation_task_id_from_response(response)
        video_url = _video_url_from_response(response)
        download_result: dict[str, Any] = {}
        if workflow_id is not None and segment_order is not None:
            download_result = self._download_remote_asset(
                video_url,
                Path("final") / workflow_id / f"segment-{segment_order}.mp4",
            )
        return {
            "provider": "volcengine-final-video-generation",
            "task_id": response_task_id,
            "task_query_url": task_url,
            "status": response.get("status", "unknown"),
            "url": video_url,
            "remote_url": video_url,
            **download_result,
            "raw_response": response,
        }

    def retrieve_video_generation_task(self, task_id: str) -> dict[str, Any]:
        return self.retrieve_seedance_task(task_id)

    def retrieve_storyboard_video_task(
        self,
        task_id: str,
        workflow_id: str,
        source_assets: list[str] | None = None,
        duration_seconds: int | None = None,
        segment_order: int = 1,
        scene_id: str | None = None,
        prompt: str | None = None,
        resolution: str | None = None,
        ratio: str | None = None,
        download_media: bool = True,
        output_relative_path: Path | str | None = None,
    ) -> dict[str, Any]:
        order = int(segment_order)
        task_url = _video_generation_task_url(
            self._settings.video_generation_endpoint or "",
            task_id,
        )
        response = self._get_video_generation_task_response(task_url)
        response_task_id = _optional_video_generation_task_id_from_response(response) or task_id
        video_url = _video_url_from_response(response)
        normalized_resolution = _normalize_video_resolution(
            resolution or self._settings.video_generation_resolution
        )
        normalized_ratio = _normalize_video_ratio(ratio or DEFAULT_VIDEO_RATIO)
        relative_video_path = (
            Path(output_relative_path)
            if output_relative_path is not None
            else Path("videos") / workflow_id / "segments" / f"segment-{order}.mp4"
        )
        if download_media:
            if video_url:
                download_result = self._download_remote_asset(video_url, relative_video_path)
            elif str(response.get("status") or "").strip().lower() in {
                "succeeded",
                "completed",
            }:
                download_result = {
                    "local_path": None,
                    "download_status": "failed",
                    "download_error_code": "provider_result_unavailable",
                    "download_error": "Remote provider result is unavailable.",
                    "download_retryable": False,
                    "download_http_status": None,
                    "download_expected_bytes": None,
                    "download_received_bytes": 0,
                }
            else:
                download_result = {
                    "local_path": None,
                    "download_status": "waiting_for_remote_url",
                }
        else:
            download_result = {
                "local_path": None,
                "download_status": "skipped",
            }
        asset = _storyboard_video_segment_asset(
            segment={
                "order": order,
                "scene_id": scene_id or f"scene-{order}",
                "prompt": prompt or "",
                "duration_seconds": duration_seconds
                or _video_duration_from_response(response)
                or 10,
                "input_asset_ids": source_assets or [],
                "source_assets": source_assets or [],
            },
            workflow_id=workflow_id,
            provider="volcengine-seedance-storyboard-segment",
            model=self._settings.video_generation_model,
            task_id=response_task_id,
            task_query_url=task_url,
            response=response,
            remote_url=video_url,
            resolution=normalized_resolution,
            ratio=normalized_ratio,
            download_result=download_result,
            metadata_path=(
                relative_video_path.with_suffix(".json")
                if output_relative_path is not None
                else None
            ),
        )
        _write_json_metadata(self._settings.media_data_dir, asset["metadata_path"], asset)
        return asset

    def compose_video_segments(
        self,
        segments: list[dict[str, Any]],
        workflow_id: str,
    ) -> dict[str, Any]:
        return self.compose_final_video(
            {
                "asset_id": "final-video-generation",
                "segments": segments,
                "composition_status": "ready"
                if _composed_video_url(segments)
                else "waiting_for_segments",
            },
            sum(int(segment.get("duration_seconds", 0)) for segment in segments),
            workflow_id,
        )

    def _get_video_generation_task_response(self, url: str) -> dict[str, Any]:
        request = urllib_request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._settings.video_generation_api_key}",
                "Content-Type": "application/json",
            },
            method="GET",
        )
        try:
            with urllib_request.urlopen(request, timeout=120) as response:
                response_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            raise _media_api_error(
                exc=exc,
                endpoint=url,
                payload=None,
            ) from exc
        return json.loads(response_body) if response_body else {}

    def compose_final_video(
        self,
        synchronized_asset: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]:
        segments = synchronized_asset.get("segments")
        if isinstance(segments, list) and segments:
            return self._compose_downloaded_video_segments(
                synchronized_asset,
                duration_seconds,
                workflow_id,
            )

        endpoint = self._settings.composition_endpoint
        final_asset = {
            "provider": self._settings.composition_provider,
            "asset_id": "final-ad-video",
            "source_asset": synchronized_asset["asset_id"],
            "duration_seconds": duration_seconds,
            "mime_type": "video/mp4",
            "operation": "assemble generated assets on a deterministic editing timeline",
            "uses_llm_generation": False,
            "status": "submitted",
        }
        if endpoint:
            final_asset["url"] = _url(endpoint, workflow_id, "final/final-ad-video.mp4")
        else:
            final_asset["local_path"] = f"final/{workflow_id}/final-ad-video.mp4"
        return final_asset

    def _compose_downloaded_video_segments(
        self,
        synchronized_asset: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]:
        return compose_downloaded_video_segments(
            settings=self._settings,
            synchronized_asset=synchronized_asset,
            duration_seconds=duration_seconds,
            workflow_id=workflow_id,
        )
