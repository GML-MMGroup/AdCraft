from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json
import sys
from typing import Protocol, TextIO

from app.services.v2_chat_planning_canary import (
    DEFAULT_CHAT_PLANNING_CANARY_FIXTURE,
    V2ChatPlanningCanaryError,
    V2ChatPlanningCanaryResult,
    V2ChatPlanningCanaryService,
)


class _CanaryService(Protocol):
    def run(self, fixture_id: str) -> V2ChatPlanningCanaryResult: ...


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    service: _CanaryService | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = _parser().parse_args(argv)
    canary = service or V2ChatPlanningCanaryService()
    try:
        result = canary.run(args.fixture)
    except V2ChatPlanningCanaryError as exc:
        print(
            json.dumps(
                {
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=stderr,
        )
        return 1
    print(json.dumps(asdict(result), ensure_ascii=True, sort_keys=True), file=stdout)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the credentialed V2 chat planning-only canary.",
    )
    parser.add_argument("--fixture", default=DEFAULT_CHAT_PLANNING_CANARY_FIXTURE)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
