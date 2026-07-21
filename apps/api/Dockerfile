# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.10.20-slim-trixie

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN python - <<'PY'
import re
import subprocess


def command(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def version(tool: str) -> tuple[int, ...]:
    output = command(tool, "-version")
    match = re.search(rf"{re.escape(tool)} version (\d+(?:\.\d+)+)", output)
    if match is None:
        raise SystemExit(f"Unable to determine {tool} version: {output.splitlines()[0]}")
    parsed = tuple(int(part) for part in match.group(1).split("."))
    if not (6, 1) <= parsed < (8,):
        raise SystemExit(f"{tool} {match.group(1)} is outside the supported range >=6.1,<8")
    return parsed


ffmpeg_version = version("ffmpeg")
ffprobe_version = version("ffprobe")
if ffmpeg_version[0] != ffprobe_version[0]:
    raise SystemExit(f"ffmpeg {ffmpeg_version} and ffprobe {ffprobe_version} have different major versions")

encoders = command("ffmpeg", "-hide_banner", "-encoders")
if not re.search(r"^\s*[.A-Z]{2,7}\s+(libx264|libopenh264)\b", encoders, re.MULTILINE):
    raise SystemExit("FFmpeg is missing an allowed H.264 encoder (libx264 or libopenh264)")
if not re.search(r"^\s*[.A-Z]{2,7}\s+aac\b", encoders, re.MULTILINE):
    raise SystemExit("FFmpeg is missing the AAC encoder")

print(f"Verified FFmpeg toolchain: ffmpeg {ffmpeg_version}, ffprobe {ffprobe_version}")
PY

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY main.py ./main.py

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
