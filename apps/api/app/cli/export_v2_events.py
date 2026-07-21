"""Export V2 SQLite event histories to a caller-selected offline directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.persistence.database import create_v2_database
from app.persistence.event_repository import EventRepository
from app.persistence.errors import V2PersistenceError


def export_v2_events(*, data_dir: Path, output_dir: Path) -> list[Path]:
    """Export persisted events without reading or overwriting legacy source files."""

    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise V2PersistenceError(
            "v2_event_export_output_not_empty",
            "V2 event export requires an empty output directory.",
            stage="event_export",
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    database = create_v2_database(data_dir)
    try:
        repository = EventRepository(database)
        exported_paths: list[Path] = []
        for workflow_id in repository.workflow_ids():
            output_path = output_dir / "v2" / "runs" / workflow_id / "events.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    [event.model_dump(mode="json") for event in repository.list_after(workflow_id)],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            exported_paths.append(output_path)
        return exported_paths
    finally:
        database.dispose()


def main() -> int:
    """Run the explicit offline export command."""

    parser = argparse.ArgumentParser(description="Export V2 SQLite event histories.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    export_v2_events(data_dir=arguments.data_dir, output_dir=arguments.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
