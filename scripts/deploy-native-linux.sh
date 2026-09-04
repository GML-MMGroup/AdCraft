#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/native-linux-common.sh
source "$SCRIPT_DIR/lib/native-linux-common.sh"

native_stage 1 8 "检查项目文件、系统工具和端口……"
native_validate_project
native_require_command uv "请先按原生部署教程安装 uv。"
native_verify_node
native_require_command curl "请安装 curl 后重新运行。"
native_require_command setsid "请安装 util-linux 后重新运行。"
native_verify_ffmpeg
NATIVE_SUBTITLE_FONT_PATH="$(native_resolve_subtitle_font)"
native_info "已选择字幕字体：$NATIVE_SUBTITLE_FONT_PATH。"

NATIVE_API_PORT="${ADCRAFT_NATIVE_API_PORT:-8000}"
NATIVE_AGENT_PORT="${ADCRAFT_NATIVE_AGENT_PORT:-8765}"
NATIVE_WEB_PORT="${ADCRAFT_NATIVE_WEB_PORT:-5189}"
native_validate_port "$NATIVE_API_PORT" || native_die "API 端口无效：$NATIVE_API_PORT。"
native_validate_port "$NATIVE_AGENT_PORT" || native_die "Agent 端口无效：$NATIVE_AGENT_PORT。"
native_validate_port "$NATIVE_WEB_PORT" || native_die "Web 端口无效：$NATIVE_WEB_PORT。"
[[ "$NATIVE_API_PORT" != "$NATIVE_AGENT_PORT" && "$NATIVE_API_PORT" != "$NATIVE_WEB_PORT" && "$NATIVE_AGENT_PORT" != "$NATIVE_WEB_PORT" ]] \
  || native_die "API、Agent 和 Web 端口不能相同。"
NATIVE_LOCAL_SETTINGS_ALLOWED_ORIGINS="http://127.0.0.1:$NATIVE_WEB_PORT,http://localhost:$NATIVE_WEB_PORT,http://[::1]:$NATIVE_WEB_PORT"

native_stop_process API "$NATIVE_API_PID_FILE"
native_stop_process Agent "$NATIVE_AGENT_PID_FILE"
native_stop_process Web "$NATIVE_WEB_PID_FILE"
if native_port_is_listening "$NATIVE_API_PORT"; then
  native_die "API 端口 $NATIVE_API_PORT 已被其他程序占用。可用 ADCRAFT_NATIVE_API_PORT 指定其他端口。"
fi
if native_port_is_listening "$NATIVE_AGENT_PORT"; then
  native_die "Agent 端口 $NATIVE_AGENT_PORT 已被其他程序占用。可用 ADCRAFT_NATIVE_AGENT_PORT 指定其他端口。"
fi
if native_port_is_listening "$NATIVE_WEB_PORT"; then
  native_die "Web 端口 $NATIVE_WEB_PORT 已被其他程序占用。可用 ADCRAFT_NATIVE_WEB_PORT 指定其他端口。"
fi

native_stage 2 8 "准备本地配置和运行目录……"
native_initialize_runtime
native_initialize_env_file "$NATIVE_API_DIR/.env"
native_initialize_env_file "$NATIVE_WEB_DIR/.env"

native_stage 3 8 "安装后端依赖（uv sync）；uv 会显示下载和安装进度……"
(
  cd "$NATIVE_API_DIR"
  uv sync
)

native_stage 4 8 "安装 Agent 运行时依赖（npm ci）；npm 会显示下载和安装进度……"
(
  cd "$NATIVE_AGENT_DIR"
  npm ci --progress=true
)

native_stage 5 8 "安装前端依赖（npm ci）；npm 会显示下载和安装进度……"
(
  cd "$NATIVE_WEB_DIR"
  npm ci --progress=true
)

native_write_state
native_stage 6 8 "启动 Agent 运行时：127.0.0.1:$NATIVE_AGENT_PORT……"
(
  cd "$NATIVE_AGENT_DIR"
  exec setsid env \
    AGENT_RUNTIME_HOST=127.0.0.1 \
    AGENT_RUNTIME_PORT="$NATIVE_AGENT_PORT" \
    AGENT_RUNTIME_PYTHON_BASE_URL="http://127.0.0.1:$NATIVE_API_PORT" \
    AGENT_RUNTIME_INTERNAL_TOKEN="$NATIVE_AGENT_RUNTIME_TOKEN" \
    node --import tsx src/main.ts
) > "$NATIVE_AGENT_LOG_FILE" 2>&1 &
printf '%s\n' "$!" > "$NATIVE_AGENT_PID_FILE"

native_wait_for_url Agent "$(native_agent_health_url)" "$NATIVE_AGENT_RUNTIME_TOKEN"
native_stage 7 8 "启动 API：127.0.0.1:$NATIVE_API_PORT……"
(
  cd "$NATIVE_API_DIR"
  exec setsid env \
    MEDIA_DATA_DIR="$NATIVE_API_DATA_DIR" \
    FFMPEG_PATH="$(command -v ffmpeg)" \
    FFPROBE_PATH="$(command -v ffprobe)" \
    FINAL_COMPOSITION_SUBTITLE_FONT_PATH="$NATIVE_SUBTITLE_FONT_PATH" \
    LOCAL_SETTINGS_ALLOWED_ORIGINS="$NATIVE_LOCAL_SETTINGS_ALLOWED_ORIGINS" \
    AGENT_RUNTIME_BASE_URL="http://127.0.0.1:$NATIVE_AGENT_PORT" \
    AGENT_RUNTIME_INTERNAL_TOKEN="$NATIVE_AGENT_RUNTIME_TOKEN" \
    uv run uvicorn main:app --host 127.0.0.1 --port "$NATIVE_API_PORT" --reload --reload-dir app
) > "$NATIVE_API_LOG_FILE" 2>&1 &
printf '%s\n' "$!" > "$NATIVE_API_PID_FILE"

native_wait_for_url API "$(native_api_health_url)"
native_stage 8 8 "启动网页：127.0.0.1:$NATIVE_WEB_PORT……"
(
  cd "$NATIVE_WEB_DIR"
  exec setsid env BACKEND_ORIGIN="http://127.0.0.1:$NATIVE_API_PORT" \
    npm run dev -- --host 127.0.0.1 --port "$NATIVE_WEB_PORT"
) > "$NATIVE_WEB_LOG_FILE" 2>&1 &
printf '%s\n' "$!" > "$NATIVE_WEB_PID_FILE"

native_wait_for_url Web "$(native_url)"
native_info "原生部署成功：$(native_url)"
native_info "日志：scripts/logs-native-linux.sh；停止：scripts/stop-native-linux.sh"
native_open_browser "$(native_url)"
