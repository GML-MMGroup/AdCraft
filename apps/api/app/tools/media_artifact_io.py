from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any


def _write_character_metadata(data_dir: Path, asset: dict[str, Any]) -> None:
    _write_json_metadata(data_dir, str(asset["metadata_path"]), asset)


def _write_json_metadata(
    data_dir: Path,
    relative_path: str | Path,
    metadata: dict[str, Any],
) -> None:
    metadata_path = data_dir / relative_path
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_base64_asset(
    data_dir: Path,
    image_base64: str,
    relative_path: Path,
) -> dict[str, Any]:
    encoded = image_base64.split(",", 1)[1] if image_base64.startswith("data:") else image_base64
    output_path = data_dir / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(encoded))
    return {
        "local_path": relative_path.as_posix(),
        "download_status": "decoded_base64",
    }


def _save_artifact(
    data_dir: Path,
    category: str,
    workflow_id: str,
    filename: str,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    relative_path = Path(category) / workflow_id / filename
    output_path = data_dir / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    saved_artifact = {**artifact, "local_path": relative_path.as_posix()}
    output_path.write_text(
        json.dumps(saved_artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return saved_artifact
