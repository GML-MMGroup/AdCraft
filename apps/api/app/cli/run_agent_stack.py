"""Run FastAPI and the private Pi Agent runtime as supervised sibling processes."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from types import FrameType
from typing import Any, Callable, Mapping
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.core.config import PROJECT_ROOT, Settings
from app.services.pi_agent_runtime_client import PiAgentRuntimeClient, PiAgentRuntimeError


class AgentStackSupervisorError(RuntimeError):
    """Bounded startup failure for the local two-process runtime."""


@dataclass
class SupervisedChild:
    """One owned process group or one compatible external runtime."""

    name: str
    command: tuple[str, ...]
    cwd: Any
    process: Any | None
    owned: bool = True

    def poll(self) -> int | None:
        return self.process.poll() if self.process is not None else None


def build_child_commands(settings: Settings) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not settings.agent_runtime_internal_token:
        raise AgentStackSupervisorError(
            "agent_internal_auth_unconfigured: AGENT_RUNTIME_INTERNAL_TOKEN is required."
        )
    return (
        ("uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"),
        ("node", "--import", "tsx", "src/main.ts"),
    )


def validate_child_executables(
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> None:
    for executable in ("uv", "node"):
        if which(executable) is None:
            raise AgentStackSupervisorError(
                f"agent_runtime_dependency_unavailable: {executable} is required."
            )


def _sidecar_start_mode(
    *,
    runtime_compatible: Callable[[], bool],
    port_available: Callable[[], bool],
) -> str:
    if runtime_compatible():
        return "existing"
    if not port_available():
        raise AgentStackSupervisorError(
            "agent_runtime_port_incompatible: "
            "the Agent runtime port is occupied by an incompatible service."
        )
    return "launch"


def main() -> None:
    settings = Settings.from_env()
    backend_command, sidecar_command = build_child_commands(settings)
    validate_child_executables()
    environment = os.environ.copy()
    sidecar_mode = _sidecar_start_mode(
        runtime_compatible=lambda: _runtime_compatible(settings),
        port_available=lambda: _runtime_port_available(settings),
    )
    children = [
        _launch_child(
            "backend",
            backend_command,
            cwd=PROJECT_ROOT,
            environment=environment,
        ),
        (
            SupervisedChild(
                name="agent-runtime",
                command=sidecar_command,
                cwd=PROJECT_ROOT / "agent",
                process=None,
                owned=False,
            )
            if sidecar_mode == "existing"
            else _launch_child(
                "agent-runtime",
                sidecar_command,
                cwd=PROJECT_ROOT / "agent",
                environment=environment,
            )
        ),
    ]
    stopping = False

    def shutdown(_: int, __: FrameType | None) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for child in children:
            _terminate_child(child)

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
        failed = [
            child.process.returncode
            for child in children
            if child.process is not None
            and child.process.returncode not in {0, -15, -signal.SIGTERM}
        ]
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
    sidecar = children[1]
    if isinstance(sidecar, SupervisedChild) and not sidecar.owned:
        return restart_count
    process = sidecar.process if isinstance(sidecar, SupervisedChild) else sidecar
    if process.poll() is None:
        return restart_count
    if restart_count >= 3:
        raise AgentStackSupervisorError(
            "agent_runtime_restart_budget_exceeded: "
            "the Agent runtime exceeded its bounded restart budget."
        )

    next_restart_count = restart_count + 1
    sleep(min(float(2 ** (next_restart_count - 1)), 4.0))
    replacement = popen(
        sidecar_command,
        cwd=PROJECT_ROOT / "agent",
        env=dict(environment),
        start_new_session=(os.name == "posix"),
    )
    children[1] = (
        SupervisedChild(
            name=sidecar.name,
            command=sidecar_command,
            cwd=PROJECT_ROOT / "agent",
            process=replacement,
        )
        if isinstance(sidecar, SupervisedChild)
        else replacement
    )
    return next_restart_count


def _wait_for_health(settings: Settings, children: list[SupervisedChild]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(child.poll() is not None for child in children):
            raise AgentStackSupervisorError(
                "agent_stack_child_failed: a supervised child exited during startup."
            )
        if _healthy("http://127.0.0.1:8000/api/v1/health") and _runtime_compatible(settings):
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


def _launch_child(
    name: str,
    command: tuple[str, ...],
    *,
    cwd: Any,
    environment: Mapping[str, str],
    popen: Callable[..., Any] = subprocess.Popen,
) -> SupervisedChild:
    return SupervisedChild(
        name=name,
        command=command,
        cwd=cwd,
        process=popen(
            command,
            cwd=cwd,
            env=dict(environment),
            start_new_session=(os.name == "posix"),
        ),
    )


def _terminate_child(
    child: SupervisedChild,
    *,
    timeout_seconds: float = 10.0,
    getpgid: Callable[[int], int] = os.getpgid,
    killpg: Callable[[int, int], None] = os.killpg,
) -> None:
    process = child.process
    if not child.owned or process is None or process.poll() is not None:
        return
    if os.name == "posix":
        process_group = getpgid(process.pid)
        killpg(process_group, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
        return
    except (subprocess.TimeoutExpired, TimeoutError):
        pass
    if os.name == "posix":
        killpg(process_group, signal.SIGKILL)
    else:
        process.kill()


def _runtime_compatible(settings: Settings) -> bool:
    client = PiAgentRuntimeClient(
        base_url=settings.agent_runtime_base_url,
        internal_token=settings.agent_runtime_internal_token or "",
        connect_timeout_seconds=0.5,
        read_timeout_seconds=0.5,
    )
    try:
        client.health()
    except PiAgentRuntimeError:
        return False
    finally:
        client.close()
    return True


def _runtime_port_available(settings: Settings) -> bool:
    parsed = urlparse(settings.agent_runtime_base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return False
    except OSError:
        return True


if __name__ == "__main__":
    try:
        main()
    except AgentStackSupervisorError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
