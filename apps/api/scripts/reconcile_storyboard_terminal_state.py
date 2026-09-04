"""Dry-run or apply exact Storyboard terminal convergence for one Workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.persistence.database import create_v2_database  # noqa: E402
from app.persistence.event_repository import EventRepository  # noqa: E402
from app.services.agent_canvas_storyboard_terminal_reconciliation import (  # noqa: E402
    AgentCanvasStoryboardTerminalReconciliationService,
)


def main(
    argv: list[str] | None = None,
    *,
    data_dir_override: Path | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-digest")
    arguments = parser.parse_args(argv)
    if arguments.apply and not arguments.expected_plan_digest:
        parser.error("--expected-plan-digest is required with --apply")
    if arguments.dry_run and arguments.expected_plan_digest:
        parser.error("--expected-plan-digest is accepted only with --apply")

    data_dir = data_dir_override or get_settings().media_data_dir
    database = create_v2_database(data_dir)
    try:
        service = AgentCanvasStoryboardTerminalReconciliationService(
            database,
            EventRepository(database),
        )
        result = (
            service.apply(
                workflow_id=arguments.workflow_id,
                expected_plan_digest=arguments.expected_plan_digest,
            )
            if arguments.apply
            else service.dry_run(workflow_id=arguments.workflow_id)
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    finally:
        database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
