from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

from app.core.config import get_settings
from app.schemas.workflow_v2_prompt_eval import V2PromptEvalStage
from app.services.v2_prompt_eval_runner import V2PromptEvalRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay deterministic V2 prompt eval fixtures.")
    parser.add_argument("--fixture", required=True, help="Prompt eval fixture id.")
    parser.add_argument("--output", required=True, help="Path to write report JSON.")
    parser.add_argument("--data-dir", help="Override media data dir for eval artifacts.")
    parser.add_argument("--profile", default="current", help="Prompt profile id.")
    parser.add_argument("--mode", choices=["mock", "real"], default="mock", help="Eval mode.")
    parser.add_argument(
        "--stages",
        nargs="+",
        default=["all"],
        help="Eval stages, for example: provider_payload or script_writer expert_brief.",
    )
    args = parser.parse_args()

    settings = get_settings()
    settings = replace(
        settings,
        agno_mock_mode=args.mode == "mock",
        media_data_dir=Path(args.data_dir) if args.data_dir else settings.media_data_dir,
    )
    report = V2PromptEvalRunner(settings).run_fixture(
        args.fixture,
        prompt_profile_id=args.profile,
        mode=args.mode,
        selected_stages=cast(list[V2PromptEvalStage], [str(stage) for stage in args.stages]),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
