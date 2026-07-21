from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from app.core.config import get_settings
from app.services.v2_workflow_acceptance import V2WorkflowAcceptanceRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic V2 workflow acceptance checks.")
    parser.add_argument("--fixture", required=True, help="Acceptance fixture id.")
    parser.add_argument("--output", required=True, help="Path to write acceptance report JSON.")
    parser.add_argument("--data-dir", help="Override media data dir for acceptance artifacts.")
    args = parser.parse_args()

    settings = get_settings()
    settings = replace(
        settings,
        agno_mock_mode=True,
        media_data_dir=Path(args.data_dir) if args.data_dir else settings.media_data_dir,
    )
    report = V2WorkflowAcceptanceRunner(settings).run_fixture(args.fixture)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)
    if report.status != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()
