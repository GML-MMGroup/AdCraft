#!/usr/bin/env bash

set -Eeuo pipefail

NATIVE_COMMON_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NATIVE_PROJECT_ROOT="$(cd -- "$NATIVE_COMMON_DIR/../.." && pwd)"
NATIVE_API_DIR="$NATIVE_PROJECT_ROOT/apps/api"
NATIVE_WEB_DIR="$NATIVE_PROJECT_ROOT/apps/web"
NATIVE_RUNTIME_DIR="$NATIVE_PROJECT_ROOT/runtime-data/native"
NATIVE_API_DATA_DIR="$NATIVE_PROJECT_ROOT/runtime-data/api"
NATIVE_STATE_FILE="$NATIVE_RUNTIME_DIR/native.env"
NATIVE_API_PID_FILE="$NATIVE_RUNTIME_DIR/api.pid"
NATIVE_WEB_PID_FILE="$NATIVE_RUNTIME_DIR/web.pid"
NATIVE_API_LOG_FILE="$NATIVE_RUNTIME_DIR/api.log"
NATIVE_WEB_LOG_FILE="$NATIVE_RUNTIME_DIR/web.log"

NATIVE_API_PORT=""
NATIVE_WEB_PORT=""

native_info() {
  printf '[AdCraft] %s\n' "$*"
}

native_stage() {
  local current="$1"
  local total="$2"
  local message="$3"
  printf '\n[AdCraft] [%s/%s] %s\n' "$current" "$total" "$message"
}

native_die() {
  printf '[AdCraft] ERROR: %s\n' "$*" >&2
  exit 1
}

native_validate_project() {
  [[ -f "$NATIVE_API_DIR/pyproject.toml" ]] \
    || native_die "缺少 apps/api/pyproject.toml，请从完整的 AdCraft 项目中运行脚本。"
  [[ -f "$NATIVE_API_DIR/.env.example" ]] \
    || native_die "缺少 apps/api/.env.example。"
  [[ -f "$NATIVE_WEB_DIR/package.json" ]] \
    || native_die "缺少 apps/web/package.json。"
  [[ -f "$NATIVE_WEB_DIR/package-lock.json" ]] \
    || native_die "缺少 apps/web/package-lock.json。"
  [[ -f "$NATIVE_WEB_DIR/.env.example" ]] \
    || native_die "缺少 apps/web/.env.example。"
}

native_initialize_env_file() {
  local target="$1"
  local example="$target.example"

  if [[ -e "$target" || -L "$target" ]]; then
    [[ -f "$target" && ! -L "$target" ]] \
      || native_die "${target#"$NATIVE_PROJECT_ROOT/"} 已存在但不是普通文件。"
    return
  fi

  cp "$example" "$target" \
    || native_die "无法从 ${example#"$NATIVE_PROJECT_ROOT/"} 创建 ${target#"$NATIVE_PROJECT_ROOT/"}。"
  chmod 600 "$target" \
    || native_die "无法保护 ${target#"$NATIVE_PROJECT_ROOT/"} 的权限。"
  native_info "已从示例创建 ${target#"$NATIVE_PROJECT_ROOT/"}。"
}

native_require_command() {
  local command_name="$1"
  local installation_hint="$2"
  command -v "$command_name" >/dev/null 2>&1 \
    || native_die "未找到 $command_name。$installation_hint"
}

native_verify_node() {
  local node_version node_major
  native_require_command node "请先按原生部署教程安装 Node.js 22。"
  native_require_command npm "请安装与 Node.js 配套的 npm。"
  node_version="$(node --version 2>/dev/null | sed -nE 's/^v([0-9]+)(\.[0-9]+){1,2}.*/\1/p')"
  [[ "$node_version" =~ ^[0-9]+$ ]] || native_die "无法识别 Node.js 版本。"
  node_major="$node_version"
  (( 10#$node_major == 22 )) || native_die "需要 Node.js 22，当前为 $(node --version)。"
  native_info "已验证 Node.js：$(node --version)。"
}

native_version_in_supported_range() {
  local version="$1"
  local major minor remainder
  IFS=. read -r major minor remainder <<< "$version"
  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1
  (( (10#$major == 6 && 10#$minor >= 1) || 10#$major == 7 ))
}

native_tool_version() {
  local tool="$1"
  "$tool" -version 2>/dev/null | sed -nE "1{s/^${tool//\//\\/} version ([0-9]+(\.[0-9]+)+).*/\1/p;}"
}

native_verify_ffmpeg() {
  local ffmpeg_version ffprobe_version
  native_require_command ffmpeg "请按原生部署教程安装兼容的 FFmpeg 6.1–7.x，并确保它在 PATH 中。"
  native_require_command ffprobe "请安装与 FFmpeg 同一发行版中的 ffprobe，并确保它在 PATH 中。"

  ffmpeg_version="$(native_tool_version ffmpeg)"
  ffprobe_version="$(native_tool_version ffprobe)"
  native_version_in_supported_range "$ffmpeg_version" \
    || native_die "FFmpeg 版本必须在 >=6.1,<8，当前为 ${ffmpeg_version:-unknown}。"
  native_version_in_supported_range "$ffprobe_version" \
    || native_die "ffprobe 版本必须在 >=6.1,<8，当前为 ${ffprobe_version:-unknown}。"
  [[ "${ffmpeg_version%%.*}" == "${ffprobe_version%%.*}" ]] \
    || native_die "ffmpeg 和 ffprobe 主版本不一致：$ffmpeg_version / $ffprobe_version。"

  LC_ALL=C ffmpeg -hide_banner -encoders 2>/dev/null \
    | grep -Eq '^[[:space:]]*[.A-Z]{2,7}[[:space:]]+(libx264|libopenh264)([[:space:]]|$)' \
    || native_die "FFmpeg 缺少允许的 H.264 编码器（libx264 或 libopenh264）。"
  LC_ALL=C ffmpeg -hide_banner -encoders 2>/dev/null \
    | grep -Eq '^[[:space:]]*[.A-Z]{2,7}[[:space:]]+aac([[:space:]]|$)' \
    || native_die "FFmpeg 缺少 AAC 编码器。"
  native_info "已验证 FFmpeg 工具链：ffmpeg $ffmpeg_version，ffprobe $ffprobe_version。"
}

native_initialize_runtime() {
  mkdir -p "$NATIVE_RUNTIME_DIR" "$NATIVE_API_DATA_DIR" \
    || native_die "无法创建 runtime-data/native 或 runtime-data/api。"
  chmod 700 "$NATIVE_RUNTIME_DIR" "$NATIVE_API_DATA_DIR" \
    || native_die "无法保护原生运行数据目录。"
}

native_validate_port() {
  local port="$1"
  [[ "$port" =~ ^[0-9]+$ ]] && (( 10#$port >= 1024 && 10#$port <= 65535 ))
}

native_port_is_listening() {
  local port="$1"
  ss -ltn "sport = :$port" 2>/dev/null | tail -n +2 | grep -q .
}

native_pid_is_running() {
  local pid_file="$1"
  local pid
  [[ -f "$pid_file" ]] || return 1
  pid="$(<"$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

native_remove_stale_pid_file() {
  local pid_file="$1"
  if [[ -e "$pid_file" ]] && ! native_pid_is_running "$pid_file"; then
    rm -f "$pid_file"
  fi
}

native_stop_process() {
  local label="$1"
  local pid_file="$2"
  local pid deadline

  native_remove_stale_pid_file "$pid_file"
  [[ -f "$pid_file" ]] || return 0
  pid="$(<"$pid_file")"
  native_info "停止原生 $label 进程（PID $pid）……"
  kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  deadline=$((SECONDS + 15))
  while kill -0 "$pid" 2>/dev/null && (( SECONDS < deadline )); do
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

native_write_state() {
  local temporary_file
  temporary_file="$(mktemp "$NATIVE_RUNTIME_DIR/.native.env.XXXXXX")" \
    || native_die "无法创建原生运行状态文件。"
  printf 'ADCRAFT_NATIVE_API_PORT=%s\nADCRAFT_NATIVE_WEB_PORT=%s\n' \
    "$NATIVE_API_PORT" "$NATIVE_WEB_PORT" > "$temporary_file"
  chmod 600 "$temporary_file"
  mv -f "$temporary_file" "$NATIVE_STATE_FILE"
}

native_load_state() {
  local line key value seen_api=0 seen_web=0
  [[ -f "$NATIVE_STATE_FILE" ]] \
    || native_die "缺少 runtime-data/native/native.env，请先运行 scripts/deploy-native-linux.sh。"
  NATIVE_API_PORT=""
  NATIVE_WEB_PORT=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^(ADCRAFT_NATIVE_API_PORT|ADCRAFT_NATIVE_WEB_PORT)=([0-9]+)$ ]] \
      || native_die "native.env 格式无效。"
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      ADCRAFT_NATIVE_API_PORT)
        (( seen_api == 0 )) || native_die "native.env 包含重复 API 端口。"
        NATIVE_API_PORT="$value"
        seen_api=1
        ;;
      ADCRAFT_NATIVE_WEB_PORT)
        (( seen_web == 0 )) || native_die "native.env 包含重复 Web 端口。"
        NATIVE_WEB_PORT="$value"
        seen_web=1
        ;;
    esac
  done < "$NATIVE_STATE_FILE"
  (( seen_api && seen_web )) || native_die "native.env 缺少端口字段。"
  native_validate_port "$NATIVE_API_PORT" && native_validate_port "$NATIVE_WEB_PORT" \
    || native_die "native.env 中的端口无效。"
}

native_url() {
  printf 'http://127.0.0.1:%s\n' "$NATIVE_WEB_PORT"
}

native_api_health_url() {
  printf 'http://127.0.0.1:%s/api/v1/health\n' "$NATIVE_API_PORT"
}

native_wait_for_url() {
  local label="$1"
  local url="$2"
  local deadline=$((SECONDS + 90))
  local frames=('|' '/' '-' '\\')
  local frame_index=0
  local elapsed
  while (( SECONDS < deadline )); do
    if curl --fail --silent --show-error --max-time 3 "$url" >/dev/null 2>&1; then
      printf '\r[AdCraft] [%s] 服务已就绪。                    \n' "$label"
      return 0
    fi
    elapsed=$((SECONDS - (deadline - 90)))
    printf '\r[AdCraft] [%s] 等待服务启动 %s %02ds/90s' \
      "$label" "${frames[$frame_index]}" "$elapsed"
    frame_index=$(( (frame_index + 1) % ${#frames[@]} ))
    sleep 1
  done
  printf '\n' >&2
  native_die "$label 未能在 90 秒内就绪。请运行 scripts/logs-native-linux.sh 查看日志。"
}

native_open_browser() {
  local url="$1"
  if command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    xdg-open "$url" >/dev/null 2>&1 &
  fi
}
