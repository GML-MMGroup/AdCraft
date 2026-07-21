#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/native-linux-common.sh
source "$SCRIPT_DIR/lib/native-linux-common.sh"

native_stage 1 6 "检查项目文件、系统工具和端口……"
native_validate_project
native_require_command uv "请先按原生部署教程安装 uv。"
native_verify_node
native_require_command curl "请安装 curl 后重新运行。"
native_require_command setsid "请安装 util-linux 后重新运行。"
native_verify_ffmpeg

NATIVE_API_PORT="${ADCRAFT_NATIVE_API_PORT:-8000}"
NATIVE_WEB_PORT="${ADCRAFT_NATIVE_WEB_PORT:-5189}"
native_validate_port "$NATIVE_API_PORT" || native_die "API 端口无效：$NATIVE_API_PORT。"
native_validate_port "$NATIVE_WEB_PORT" || native_die "Web 端口无效：$NATIVE_WEB_PORT。"
[[ "$NATIVE_API_PORT" != "$NATIVE_WEB_PORT" ]] || native_die "API 和 Web 端口不能相同。"
NATIVE_LOCAL_SETTINGS_ALLOWED_ORIGINS="http://127.0.0.1:$NATIVE_WEB_PORT,http://localhost:$NATIVE_WEB_PORT,http://[::1]:$NATIVE_WEB_PORT"

native_stop_process API "$NATIVE_API_PID_FILE"
native_stop_process Web "$NATIVE_WEB_PID_FILE"
if native_port_is_listening "$NATIVE_API_PORT"; then
  native_die "API 端口 $NATIVE_API_PORT 已被其他程序占用。可用 ADCRAFT_NATIVE_API_PORT 指定其他端口。"
fi
if native_port_is_listening "$NATIVE_WEB_PORT"; then
  native_die "Web 端口 $NATIVE_WEB_PORT 已被其他程序占用。可用 ADCRAFT_NATIVE_WEB_PORT 指定其他端口。"
fi

native_stage 2 6 "准备本地配置和运行目录……"
native_initialize_runtime
native_initialize_env_file "$NATIVE_API_DIR/.env"
native_initialize_env_file "$NATIVE_WEB_DIR/.env"

native_stage 3 6 "安装后端依赖（uv sync）；uv 会显示下载和安装进度……"
(
  cd "$NATIVE_API_DIR"
  uv sync
)

native_stage 4 6 "安装前端依赖（npm ci）；npm 会显示下载和安装进度……"
(
  cd "$NATIVE_WEB_DIR"
  npm ci --progress=true
)

native_write_state
native_stage 5 6 "启动 API：127.0.0.1:$NATIVE_API_PORT……"
(
  cd "$NATIVE_API_DIR"
  exec setsid env \
    MEDIA_DATA_DIR="$NATIVE_API_DATA_DIR" \
    FFMPEG_PATH="$(command -v ffmpeg)" \
    FFPROBE_PATH="$(command -v ffprobe)" \
    LOCAL_SETTINGS_ALLOWED_ORIGINS="$NATIVE_LOCAL_SETTINGS_ALLOWED_ORIGINS" \
    uv run uvicorn main:app --host 127.0.0.1 --port "$NATIVE_API_PORT" --reload --reload-dir app
) > "$NATIVE_API_LOG_FILE" 2>&1 &
printf '%s\n' "$!" > "$NATIVE_API_PID_FILE"

native_wait_for_url API "$(native_api_health_url)"
native_stage 6 6 "启动网页：127.0.0.1:$NATIVE_WEB_PORT……"
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
