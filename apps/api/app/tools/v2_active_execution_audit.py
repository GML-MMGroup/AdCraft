"""Report authoritative nonterminal V2 executions without mutating runtime state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from app.core.config import get_settings
from app.services.v2_execution_service import V2ExecutionService

ACTIVE_EXECUTION_STATUSES = {"queued", "running", "waiting"}


def audit_active_executions(data_dir: Path) -> list[dict[str, Any]]:
    """Return active execution summaries in deterministic workflow order."""

    runs_dir = data_dir / "v2" / "runs"
    if not runs_dir.is_dir():
        return []
    executions = V2ExecutionService(data_dir)
    active: list[dict[str, Any]] = []
    for workflow_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        state = executions.load_active(workflow_dir.name)
        if state is None or state.get("status") not in ACTIVE_EXECUTION_STATUSES:
            continue
        active.append(
            {
                "workflow_id": workflow_dir.name,
                "execution_id": str(state.get("execution_id") or ""),
                "status": str(state["status"]),
            }
        )
    return active


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=get_settings().media_data_dir,
        help="AdCraft data root to audit.",
    )
    arguments = parser.parse_args(argv)
    active = audit_active_executions(arguments.data_dir)
    print(
        json.dumps(
            {
                "quiescent": not active,
                "active_execution_count": len(active),
                "active_executions": active,
            },
            sort_keys=True,
        )
    )
    return 1 if active else 0


if __name__ == "__main__":
    raise SystemExit(main())
