from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import Settings

from app.tools.media_artifact_io import (
    _save_artifact,
    _write_character_metadata,
    _write_json_metadata,
)
from app.tools.media_asset_builders import (
    _assets_for_product,
    _assets_for_storyboard_scene,
    _character_specs,
    _character_turnaround_asset,
    _character_turnaround_prompt,
    _product_image_prompt,
    _product_specs,
    _scene_reference_prompt,
    _scene_specs,
    _storyboard_image_prompt,
    _storyboard_item_context,
)
from app.tools.media_subtitles import generate_subtitle_asset
from app.tools.media_composition import (
    compose_final_video,
    generate_final_video_from_multimodal_prompt,
    synchronize_audio_video,
)
from app.tools.media_provider_protocol import ARK_SEEDANCE_RESOLUTION, DEFAULT_VIDEO_RATIO
from app.tools.seedance_adapter import (
    _final_video_segments,
    _normalize_video_ratio,
    _normalize_video_resolution,
)


class MockMediaProvider:
    mode = "mock"

    def __init__(self, settings: Settings) -> None:
        self._data_dir = settings.media_data_dir

    def generate_storyboard_images(
        self,
        storyboard_scenes: list[dict[str, Any]],
        workflow_id: str,
        input_assets: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return generate_storyboard_images(
            storyboard_scenes,
            workflow_id,
            self._data_dir,
            input_assets=input_assets,
            context=context,
        )

    def generate_scene_reference_images(
        self,
        scene_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_scene_reference_images(scene_design, workflow_id, self._data_dir)

    def generate_product_images(
        self,
        product_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_product_images(product_design, workflow_id, self._data_dir)

    def generate_storyboard_video(
        self,
        storyboard_video_prompt: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_storyboard_video(
            storyboard_video_prompt,
            workflow_id,
            self._data_dir,
        )

    def generate_character_turnaround_images(
        self,
        character_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_character_turnaround_images(
            character_design,
            workflow_id,
            self._data_dir,
        )

    def generate_subtitle_asset(
        self,
        script: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_subtitle_asset(script, duration_seconds, workflow_id, self._data_dir)

    def generate_audio_assets(
        self,
        sound_effects_plan: dict[str, Any],
        voiceover_plan: dict[str, Any],
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_audio_assets(
            sound_effects_plan,
            voiceover_plan,
            bgm_plan,
            workflow_id,
            self._data_dir,
        )

    def generate_bgm_audio(
        self,
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_bgm_audio(bgm_plan, workflow_id, self._data_dir)

    def synchronize_audio_video(
        self,
        video_asset: dict[str, Any],
        audio_asset: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        return synchronize_audio_video(video_asset, audio_asset, workflow_id, self._data_dir)

    def compose_final_video(
        self,
        synchronized_asset: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]:
        return compose_final_video(
            synchronized_asset,
            duration_seconds,
            workflow_id,
            self._data_dir,
        )

    def generate_final_video_from_multimodal_prompt(
        self,
        final_video_prompt: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        return generate_final_video_from_multimodal_prompt(
            final_video_prompt,
            workflow_id,
            self._data_dir,
        )


def generate_storyboard_images(
    storyboard_scenes: list[dict[str, Any]],
    workflow_id: str,
    data_dir: Path,
    input_assets: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_assets = input_assets or []
    assets = []
    for scene in storyboard_scenes:
        prompt = _storyboard_image_prompt(scene)
        scene_input_assets = _assets_for_storyboard_scene(scene, input_assets)
        asset = _save_artifact(
            data_dir,
            "storyboards",
            workflow_id,
            f"scene-{scene['order']}.json",
            {
                "scene": scene["order"],
                "order": scene["order"],
                "asset_id": f"storyboard-image-{scene['order']}",
                "asset_type": "image",
                "role": "storyboard",
                "mime_type": "application/json",
                "status": "ready",
                "scene_id": scene.get("scene_id") or f"scene-{scene['order']}",
                "input_asset_ids": scene.get("input_asset_ids", []),
                "prompt": prompt,
            },
        )
        asset["metadata_path"] = asset["local_path"]
        asset["input_assets"] = scene_input_assets
        asset["context"] = _storyboard_item_context(scene, context or {})
        assets.append(asset)
    for asset in assets:
        _write_json_metadata(data_dir, asset["metadata_path"], asset)
    return {
        "provider": "mock-image-generator",
        "assets": assets,
        "input_assets": input_assets,
        "output_assets": assets,
    }


def generate_scene_reference_images(
    scene_design: dict[str, Any],
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    assets = []
    for index, scene in enumerate(_scene_specs(scene_design), start=1):
        asset = _save_artifact(
            data_dir,
            "scenes",
            workflow_id,
            f"scene-{index}.json",
            {
                "provider": "mock-scene-reference-generator",
                "asset_id": f"scene-reference-{index}",
                "asset_type": "image",
                "role": "scene_reference",
                "scene": index,
                "order": index,
                "scene_id": scene.get("scene_id") or f"scene-reference-{index}",
                "status": "ready",
                "download_status": "mock_metadata_only",
                "mime_type": "application/json",
                "prompt": _scene_reference_prompt(scene),
            },
        )
        asset["metadata_path"] = asset["local_path"]
        assets.append(asset)
    return {
        "provider": "mock-scene-reference-generator",
        "assets": assets,
        "output_assets": assets,
    }


def generate_product_images(
    product_design: dict[str, Any],
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    input_assets = [
        asset for asset in product_design.get("reference_assets", []) if isinstance(asset, dict)
    ]
    assets = []
    for index, product in enumerate(_product_specs(product_design), start=1):
        product_input_assets = _assets_for_product(product, input_assets)
        if (
            product.get("reference_mode") == "strict"
            and product.get("input_asset_ids")
            and not product_input_assets
        ):
            raise ValueError("product_reference_dropped")
        asset = _save_artifact(
            data_dir,
            "products",
            workflow_id,
            f"product-{index}.json",
            {
                "provider": "mock-product-image-generator",
                "asset_id": f"product-image-{index}",
                "asset_type": "image",
                "type": "image",
                "media_type": "image",
                "kind": "image",
                "role": "product_image",
                "semantic_type": "product_image",
                "entity_id": product.get("item_id") or f"product-{index}",
                "product_id": product.get("item_id") or f"product-{index}",
                "display_name": product.get("display_name") or f"Product image {index}",
                "order": product.get("order") or index,
                "status": "ready",
                "download_status": "mock_metadata_only",
                "mime_type": "application/json",
                "prompt": _product_image_prompt(product),
                "input_asset_ids": product.get("input_asset_ids", []),
                "reference_mode": product.get("reference_mode") or "strict",
                "input_assets": product_input_assets,
                "metadata": product.get("metadata")
                if isinstance(product.get("metadata"), dict)
                else {},
            },
        )
        asset["metadata_path"] = asset["local_path"]
        assets.append(asset)
    for asset in assets:
        _write_json_metadata(data_dir, asset["metadata_path"], asset)
    return {
        "provider": "mock-product-image-generator",
        "assets": assets,
        "input_assets": input_assets,
        "output_assets": assets,
    }


def generate_storyboard_video(
    storyboard_video_prompt: dict[str, Any],
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    resolution = _normalize_video_resolution(
        storyboard_video_prompt.get("output_resolution")
        or storyboard_video_prompt.get("resolution")
        or ARK_SEEDANCE_RESOLUTION
    )
    ratio = _normalize_video_ratio(
        storyboard_video_prompt.get("aspect_ratio")
        or storyboard_video_prompt.get("ratio")
        or DEFAULT_VIDEO_RATIO
    )
    segments = []
    for segment in _final_video_segments(storyboard_video_prompt):
        order = int(segment["order"])
        segment_metadata = {
            "provider": "mock-storyboard-video-segment-generator",
            "model": "mock-video-segment-generator",
            **segment,
            "resolution": resolution,
            "ratio": ratio,
            "asset_type": "video",
            "remote_url": None,
            "url": None,
            "mime_type": "application/json",
            "metadata_path": (
                Path("videos") / workflow_id / "segments" / f"segment-{order}.json"
            ).as_posix(),
            "download_status": "mock_metadata_only",
            "status": "ready",
        }
        saved_segment = _save_artifact(
            data_dir,
            f"videos/{workflow_id}/segments",
            "",
            f"segment-{order}.json",
            segment_metadata,
        )
        saved_segment["metadata_path"] = saved_segment["local_path"]
        segments.append(saved_segment)

    return {
        "provider": "mock-storyboard-video-generator",
        "model": "mock-video-segment-generator",
        "asset_id": "storyboard-video-generation",
        "segments": segments,
        "input_assets": storyboard_video_prompt.get("input_assets", []),
        "duration_seconds": storyboard_video_prompt.get("duration_seconds"),
        "resolution": resolution,
        "ratio": ratio,
        "mime_type": "application/json",
        "composition_status": "ready",
        "status": "ready",
    }


def generate_character_turnaround_images(
    character_design: dict[str, Any],
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    assets = []
    for index, character in enumerate(_character_specs(character_design), start=1):
        prompt = _character_turnaround_prompt(character)
        asset = _character_turnaround_asset(
            workflow_id=workflow_id,
            index=index,
            character=character,
            prompt=prompt,
            provider="mock-character-turnaround-generator",
            url=None,
            status="ready",
        )
        _write_character_metadata(data_dir, asset)
        assets.append(asset)
    return {
        "provider": "mock-character-turnaround-generator",
        "assets": assets,
    }


def generate_audio_assets(
    sound_effects_plan: dict[str, Any],
    voiceover_plan: dict[str, Any],
    bgm_plan: dict[str, Any],
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    sound_effects_asset = _save_artifact(
        data_dir,
        "audio",
        workflow_id,
        "sound-effects.json",
        {
            "provider": "mock-audio-generator",
            "asset_id": "sound-effects",
            "audio_plan": sound_effects_plan,
            "status": "ready",
        },
    )
    voiceover_asset = _save_artifact(
        data_dir,
        "audio",
        workflow_id,
        "voiceover.json",
        {
            "provider": "mock-audio-generator",
            "asset_id": "voiceover",
            "audio_plan": voiceover_plan,
            "status": "ready",
        },
    )
    bgm_asset = _save_artifact(
        data_dir,
        "audio",
        workflow_id,
        "bgm.json",
        {
            "provider": "mock-audio-generator",
            "asset_id": "bgm",
            "audio_plan": bgm_plan,
            "status": "ready",
        },
    )
    return _save_artifact(
        data_dir,
        "audio",
        workflow_id,
        "audio-package.json",
        {
            "provider": "mock-audio-generator",
            "asset_id": "audio-package",
            "source_assets": {
                "sound-effects": sound_effects_asset["asset_id"],
                "voiceover": voiceover_asset["asset_id"],
                "bgm": bgm_asset["asset_id"],
            },
            "assets": [sound_effects_asset, voiceover_asset, bgm_asset],
            "status": "ready",
        },
    )


def generate_bgm_audio(
    bgm_plan: dict[str, Any],
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    bgm_asset = _save_artifact(
        data_dir,
        "audio",
        workflow_id,
        "bgm.json",
        {
            "provider": "mock-bgm-generator",
            "asset_id": "bgm",
            "audio_plan": bgm_plan,
            "status": "ready",
        },
    )
    return {
        "provider": "mock-bgm-generator",
        "model": "mock-bgm",
        "assets": [bgm_asset],
        "status": "ready",
    }
