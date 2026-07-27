"""Run FastAPI and the private Pi Agent runtime as supervised sibling processes."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from types import FrameType
from typing import Any, Callable, Mapping
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.core.config import PROJECT_ROOT, Settings


class AgentStackSupervisorError(RuntimeError):
    """Bounded startup failure for the local two-process runtime."""


def build_child_commands(settings: Settings) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not settings.agent_runtime_internal_token:
        raise AgentStackSupervisorError(
            "agent_internal_auth_unconfigured: AGENT_RUNTIME_INTERNAL_TOKEN is required."
        )
    return (
        ("uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"),
        ("npm", "--prefix", "agent-runtime", "start"),
    )


def main() -> None:
    settings = Settings.from_env()
    backend_command, sidecar_command = build_child_commands(settings)
    for executable in ("uv", "node", "npm"):
        if shutil.which(executable) is None:
            raise AgentStackSupervisorError(
                f"agent_runtime_dependency_unavailable: {executable} is required."
            )

    environment = os.environ.copy()
    children = [
        subprocess.Popen(backend_command, cwd=PROJECT_ROOT, env=environment),
        subprocess.Popen(sidecar_command, cwd=PROJECT_ROOT, env=environment),
    ]
    stopping = False

    def shutdown(_: int, __: FrameType | None) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        _wait_for_health(settings, children)
        sidecar_restart_count = 0
        while children[0].poll() is None:
            sidecar_restart_count = _restart_sidecar_if_needed(
                children,
                sidecar_command=sidecar_command,
                environment=environment,
                restart_count=sidecar_restart_count,
            )
            time.sleep(0.25)
    finally:
        shutdown(signal.SIGTERM, None)
        deadline = time.monotonic() + 10
        for child in children:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                child.kill()
        failed = [child.returncode for child in children if child.returncode not in {0, -15}]
        if failed:
            raise AgentStackSupervisorError(
                "agent_stack_child_failed: a supervised child exited unexpectedly."
            )


def _restart_sidecar_if_needed(
    children: list[Any],
    *,
    sidecar_command: tuple[str, ...],
    environment: Mapping[str, str],
    restart_count: int,
    popen: Callable[..., Any] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if children[1].poll() is None:
        return restart_count
    if restart_count >= 3:
        raise AgentStackSupervisorError(
            "agent_runtime_restart_budget_exceeded: "
            "the Agent runtime exceeded its bounded restart budget."
        )

    next_restart_count = restart_count + 1
    sleep(min(float(2 ** (next_restart_count - 1)), 4.0))
    children[1] = popen(
        sidecar_command,
        cwd=PROJECT_ROOT,
        env=dict(environment),
    )
    return next_restart_count


def _wait_for_health(settings: Settings, children: list[subprocess.Popen[bytes]]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(child.poll() is not None for child in children):
            raise AgentStackSupervisorError(
                "agent_stack_child_failed: a supervised child exited during startup."
            )
        if _healthy("http://127.0.0.1:8000/api/v1/health") and _healthy(
            f"{settings.agent_runtime_base_url.rstrip('/')}/internal/v1/health",
            token=settings.agent_runtime_internal_token,
        ):
            return
        time.sleep(0.25)
    raise AgentStackSupervisorError(
        "agent_stack_health_timeout: backend and Agent runtime did not become ready."
    )


def _healthy(url: str, *, token: str | None = None) -> bool:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(url, headers=headers), timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


if __name__ == "__main__":
    try:
        main()
    except AgentStackSupervisorError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
