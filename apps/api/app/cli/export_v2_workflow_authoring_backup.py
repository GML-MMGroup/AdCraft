"""Export immutable pre-SQLite Workflow backups for an explicit rollback operation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.persistence.errors import V2PersistenceError


def export_v2_workflow_authoring_backup(
    *,
    data_dir: Path,
    workflow_ids: list[str],
    output_root: Path,
) -> dict[str, object]:
    """Copy selected immutable pre-SQLite backups into a new offline rollback root."""

    if not workflow_ids:
        raise V2PersistenceError(
            "v2_workflow_backup_export_empty_selection",
            "At least one Workflow ID is required for rollback export.",
            stage="workflow_backup_export",
        )
    if output_root.exists() and (not output_root.is_dir() or any(output_root.iterdir())):
        raise V2PersistenceError(
            "v2_workflow_backup_export_output_not_empty",
            "Workflow backup export requires an empty output directory.",
            stage="workflow_backup_export",
        )
    output_root.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, object]] = []
    for workflow_id in sorted(set(workflow_ids)):
        source = (
            data_dir
            / "v2"
            / "migration-backups"
            / "workflows"
            / workflow_id
            / "workflow.pre-sqlite.json"
        )
        if not source.is_file():
            raise V2PersistenceError(
                "v2_workflow_backup_export_missing",
                "A requested pre-SQLite Workflow backup was not found.",
                stage="workflow_backup_export",
            )
        output = output_root / "v2" / "workflows" / workflow_id / "workflow.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = source.read_bytes()
        output.write_bytes(payload)
        items.append(
            {
                "workflow_id": workflow_id,
                "source_backup_relative_path": source.relative_to(data_dir).as_posix(),
                "source_sha256": _sha256(source),
                "output_relative_path": output.relative_to(output_root).as_posix(),
                "output_sha256": _sha256(output),
            }
        )
    manifest: dict[str, object] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "includes_post_cutover_revisions": False,
        "purpose": "offline pre-SQLite rollback export; this is not an in-place live restore",
        "items": items,
    }
    (output_root / "rollback-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    """Run the explicit export-only rollback command."""

    parser = argparse.ArgumentParser(
        description="Export pre-SQLite Workflow backups; this does not restore live state."
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--workflow-id", action="append", dest="workflow_ids", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    arguments = parser.parse_args()
    export_v2_workflow_authoring_backup(
        data_dir=arguments.data_dir,
        workflow_ids=arguments.workflow_ids,
        output_root=arguments.output_root,
    )
    return 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
