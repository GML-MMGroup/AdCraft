"""Run the repository's disjoint pytest verification profiles."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import shlex
import subprocess
import sys
import time
from types import MappingProxyType
from typing import Literal, Mapping, Sequence


ProfileName = Literal["fast", "integration", "media", "e2e", "full"]


@dataclass(frozen=True)
class TestPhase:
    name: str
    marker_expression: str
    max_workers: int
    distribution: str | None


_PHASE_DEFINITIONS = {
    "fast": TestPhase(
        name="fast",
        marker_expression="not slow and not integration and not media and not e2e",
        max_workers=8,
        distribution="worksteal",
    ),
    "integration": TestPhase(
        name="integration",
        marker_expression="integration and not media and not e2e",
        max_workers=4,
        distribution="loadfile",
    ),
    "media": TestPhase(
        name="media",
        marker_expression="media and not e2e",
        max_workers=2,
        distribution="loadfile",
    ),
    "e2e": TestPhase(
        name="e2e",
        marker_expression="e2e",
        max_workers=1,
        distribution=None,
    ),
    "slow-unit": TestPhase(
        name="slow-unit",
        marker_expression="slow and not integration and not media and not e2e",
        max_workers=1,
        distribution=None,
    ),
}

PHASES: Mapping[str, TestPhase] = MappingProxyType(_PHASE_DEFINITIONS)
FULL_PHASE_ORDER = ("fast", "integration", "media", "e2e", "slow-unit")
PUBLIC_PROFILES = ("fast", "integration", "media", "e2e", "full")


def build_phase_command(phase: TestPhase) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        phase.marker_expression,
    ]
    if phase.max_workers > 1:
        command.extend(
            [
                "-n",
                "auto",
                "--maxprocesses",
                str(phase.max_workers),
                "--dist",
                phase.distribution or "loadfile",
            ]
        )
    command.extend(["--durations=20", "--durations-min=1.0", "-q", "-ra"])
    return command


def _xdist_available() -> bool:
    return importlib.util.find_spec("xdist") is not None


def run_phase(phase: TestPhase) -> int:
    command = build_phase_command(phase)
    command_text = shlex.join(command)
    if phase.max_workers > 1 and not _xdist_available():
        print(
            f"[tests:{phase.name}] pytest-xdist is not installed; run `uv add --dev pytest-xdist`.",
            file=sys.stderr,
        )
        return 2

    print(f"[tests:{phase.name}] command: {command_text}", flush=True)
    print(f"[tests:{phase.name}] started", flush=True)
    started_at = time.monotonic()
    try:
        result = subprocess.run(command, check=False)
        exit_code = result.returncode
    except KeyboardInterrupt:
        exit_code = 130
    elapsed = time.monotonic() - started_at
    print(
        f"[tests:{phase.name}] finished in {elapsed:.2f}s with exit status {exit_code}",
        flush=True,
    )
    return exit_code


def run_profile(profile: ProfileName) -> int:
    phase_names = FULL_PHASE_ORDER if profile == "full" else (profile,)
    for phase_name in phase_names:
        exit_code = run_phase(PHASES[phase_name])
        if exit_code != 0:
            return exit_code
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one canonical AdCraft pytest verification profile."
    )
    parser.add_argument("profile", choices=PUBLIC_PROFILES)
    args = parser.parse_args(argv)
    return run_profile(args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
