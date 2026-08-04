from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys
from typing import Protocol, TextIO

from app.services.v2_pi_equivalence_canary import (
    V2PiCanaryCaseId,
    V2PiCanaryReport,
    V2PiEquivalenceCanaryService,
    V2_PI_CANARY_CASE_IDS,
)


class _CanaryService(Protocol):
    def run_case(self, case_id: V2PiCanaryCaseId): ...

    def run_all(self) -> V2PiCanaryReport: ...


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    service: _CanaryService | None = None,
    stdout: TextIO = sys.stdout,
) -> int:
    args = _parser().parse_args(argv)
    canary = service or V2PiEquivalenceCanaryService()
    if args.case == "all":
        report = canary.run_all()
    else:
        result = canary.run_case(args.case)
        report = V2PiCanaryReport(
            passed=result.status == "passed",
            results=(result,),
        )
    print(json.dumps(report.to_safe_dict(), ensure_ascii=True, sort_keys=True), file=stdout)
    return 0 if report.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run media-free Pi equivalence canaries.")
    parser.add_argument("--case", choices=("all", *V2_PI_CANARY_CASE_IDS), default="all")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
