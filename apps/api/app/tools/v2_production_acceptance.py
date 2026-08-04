from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, TextIO
from uuid import uuid4

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_FIXTURE = "core_av_canary"
DEFAULT_TIMEOUT_SECONDS = 7200.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
TERMINAL_LIFECYCLES = {"completed", "blocked", "failed", "cancelled"}


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    stdout: TextIO = sys.stdout,
) -> int:
    args = _parser().parse_args(argv)
    idempotency_key = args.idempotency_key or _generated_idempotency_key()
    endpoint = "/api/v2/production-acceptance-runs"
    try:
        with httpx.Client(
            base_url=args.base_url.rstrip("/"),
            transport=transport,
            timeout=30.0,
        ) as client:
            response = client.post(
                endpoint,
                json={"fixture_id": args.fixture},
                headers={"Idempotency-Key": idempotency_key},
            )
            state = _response_json(response)
            _print_state(state, stdout=stdout, output_path=args.output)

            if not args.wait or _is_terminal(state):
                return _finish(client, state, args.output, stdout)

            deadline = now() + args.timeout_seconds
            run_id = _required_text(state, "acceptance_run_id")
            state_url = f"{endpoint}/{run_id}"
            while not _is_terminal(state):
                remaining = deadline - now()
                if remaining <= 0:
                    print("Acceptance wait timed out; backend state was not changed.", file=stdout)
                    return 2
                sleep(min(args.poll_interval_seconds, remaining))
                if now() >= deadline:
                    print("Acceptance wait timed out; backend state was not changed.", file=stdout)
                    return 2
                state = _response_json(client.get(state_url))
                _print_state(state, stdout=stdout, output_path=args.output)
            return _finish(client, state, args.output, stdout)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"Acceptance client error: {type(exc).__name__}", file=stdout)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start and observe a V2 production acceptance run through HTTP.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--idempotency-key")
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=_positive_float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
    )
    return parser


def _positive_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive number") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return value


def _response_json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("Acceptance API response must be a JSON object.")
    return payload


def _finish(
    client: httpx.Client,
    state: dict[str, Any],
    output_path: Path | None,
    stdout: TextIO,
) -> int:
    lifecycle = str(state.get("lifecycle_status") or "")
    verdict = str(state.get("technical_verdict") or "")
    if state.get("report_available"):
        report_url = state.get("report_url")
        if isinstance(report_url, str) and report_url:
            report = _response_json(client.get(report_url))
            if output_path is not None:
                _atomic_json_write(output_path, report)
                print(f"report_output={output_path}", file=stdout)
    if verdict == "passed" and lifecycle == "completed":
        return 0
    if verdict == "failed" or lifecycle in {"failed", "cancelled"}:
        return 1
    return 2


def _print_state(
    state: dict[str, Any],
    *,
    stdout: TextIO,
    output_path: Path | None,
) -> None:
    fields = (
        ("acceptance_run_id", state.get("acceptance_run_id")),
        ("workflow_id", state.get("workflow_id")),
        ("execution_id", state.get("execution_id")),
        ("lifecycle", state.get("lifecycle_status")),
        ("verdict", state.get("technical_verdict")),
        ("report_url", state.get("report_url")),
        ("review_url", state.get("review_url")),
        ("report_output", output_path),
    )
    print(
        " ".join(f"{key}={value}" for key, value in fields if value not in (None, "")),
        file=stdout,
    )


def _is_terminal(state: dict[str, Any]) -> bool:
    return str(state.get("lifecycle_status") or "") in TERMINAL_LIFECYCLES


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise KeyError(key)
    return value


def _generated_idempotency_key() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"acceptance-{stamp}-{uuid4().hex}"


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=True, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
