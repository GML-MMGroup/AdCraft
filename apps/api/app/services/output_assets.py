from typing import Any


def dedupe_output_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for asset in assets:
        keys = _output_asset_dedupe_keys(asset)
        if not keys:
            deduped.append(dict(asset))
            continue
        existing_index = next((index_by_key[key] for key in keys if key in index_by_key), None)
        if existing_index is None:
            existing_index = len(deduped)
            deduped.append(dict(asset))
            for key in keys:
                index_by_key[key] = existing_index
            continue
        deduped[existing_index] = _merge_output_asset(deduped[existing_index], asset)
        for key in _output_asset_dedupe_keys(deduped[existing_index]):
            index_by_key[key] = existing_index
    return deduped


def _output_asset_dedupe_keys(asset: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for field_name in (
        "asset_id",
        "local_path",
        "public_url",
        "remote_url",
        "url",
        "metadata_path",
    ):
        value = asset.get(field_name)
        if isinstance(value, str) and value.strip():
            keys.append(f"{field_name}:{value.strip()}")
    return keys


def _merge_output_asset(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    preferred, fallback = (
        (incoming, existing)
        if _output_asset_preference(incoming) > _output_asset_preference(existing)
        else (existing, incoming)
    )
    merged = dict(preferred)
    for key, value in fallback.items():
        if _is_missing_asset_value(merged.get(key)) and not _is_missing_asset_value(value):
            merged[key] = value
    return merged


def _output_asset_preference(asset: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        1 if asset.get("public_url") else 0,
        1 if asset.get("local_path") else 0,
        1 if asset.get("download_status") in {"downloaded", "ready"} else 0,
        sum(1 for value in asset.values() if not _is_missing_asset_value(value)),
    )


def _is_missing_asset_value(value: Any) -> bool:
    return value in (None, "", [], {})
