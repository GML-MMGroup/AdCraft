from app.schemas.assets import InputModality, WorkflowAssetReference
from app.services.canonical_assets import canonical_media_type


def classify_input_modality(assets: list[WorkflowAssetReference]) -> InputModality:
    prompt_asset_types = {
        canonical_media_type(asset.model_dump(mode="json"))
        for asset in assets
        if asset.use_as_prompt
    }
    prompt_asset_types.discard("")
    if prompt_asset_types == {"image"}:
        return "text_image"
    if prompt_asset_types == {"video"}:
        return "text_video"
    if prompt_asset_types == {"image", "video"}:
        return "text_image_video"
    return "text_only"


def multimodal_prompt_enabled(assets: list[WorkflowAssetReference]) -> bool:
    return classify_input_modality(assets) != "text_only"


def assets_for_prompt_target(
    assets: list[WorkflowAssetReference],
    target: str,
) -> list[dict[str, str | bool | list[str]]]:
    return [
        {
            "asset_id": asset.asset_id,
            "asset_type": asset.asset_type,
            "asset_role": asset.asset_role,
            "filename": asset.filename,
            "mime_type": asset.mime_type,
            "local_path": asset.local_path,
            "use_as_prompt": asset.use_as_prompt,
            "prompt_targets": asset.prompt_targets,
        }
        for asset in assets
        if asset.use_as_prompt and target in asset.prompt_targets
    ]


def selected_asset_summary(assets: list[WorkflowAssetReference]) -> list[dict[str, str | bool]]:
    return [
        {
            "asset_id": asset.asset_id,
            "asset_type": asset.asset_type,
            "asset_role": asset.asset_role,
            "filename": asset.filename,
            "local_path": asset.local_path,
            "use_as_prompt": asset.use_as_prompt,
        }
        for asset in assets
    ]
