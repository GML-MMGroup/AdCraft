#!/usr/bin/env bash

set -Eeuo pipefail

DRY_RUN=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY_RUN=1 ;;
  *) printf 'Usage: %s [--dry-run]\n' "$0" >&2; exit 2 ;;
esac

# Stop the manually started AdCraft stack without touching unrelated projects.
# The backend lives outside this checkout in the current development setup.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BACKEND_ROOT="${ADCRAFT_BACKEND_ROOT:-/data/wenwu.meng/adWorkflow}"
FRONTEND_ROOT="${ADCRAFT_FRONTEND_ROOT:-$PROJECT_ROOT/apps/web}"
STATE_FILE="$PROJECT_ROOT/runtime-data/native/native.env"

API_PORT="${ADCRAFT_NATIVE_API_PORT:-8000}"
AGENT_PORT="${ADCRAFT_NATIVE_AGENT_PORT:-8765}"
WEB_PORT="${ADCRAFT_NATIVE_WEB_PORT:-5189}"

# A native deployment records the actual ports it used. Read only port fields;
# never print or source native.env because it also contains the runtime token.
if [[ -f "$STATE_FILE" ]]; then
  while IFS='=' read -r key value; do
    case "$key" in
      ADCRAFT_NATIVE_API_PORT) [[ -n "${ADCRAFT_NATIVE_API_PORT:-}" ]] || API_PORT="$value" ;;
      ADCRAFT_NATIVE_AGENT_PORT) [[ -n "${ADCRAFT_NATIVE_AGENT_PORT:-}" ]] || AGENT_PORT="$value" ;;
      ADCRAFT_NATIVE_WEB_PORT) [[ -n "${ADCRAFT_NATIVE_WEB_PORT:-}" ]] || WEB_PORT="$value" ;;
    esac
  done < "$STATE_FILE"
fi

declare -A CANDIDATES=()

add_candidate() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  (( pid > 1 && pid != $$ )) || return 0
  [[ -d "/proc/$pid" ]] || return 0
  CANDIDATES["$pid"]=1
}

is_frontend_process() {
  local command_line="$1"
  [[ "$command_line" == *"vite"* || "$command_line" == *"npm run dev"* ]]
}

is_backend_process() {
  local command_line="$1"
  [[ "$command_line" == *"run_agent_stack"* \
    || "$command_line" == *"uvicorn app.main:app"* \
    || "$command_line" == *"uvicorn main:app"* \
    || "$command_line" == *"src/main.ts"* ]]
}

process_label() {
  local pid="$1"
  local process_cwd command_line
  process_cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  if [[ "$process_cwd" == "$FRONTEND_ROOT" ]]; then
    printf 'Web'
  elif [[ "$command_line" == *"uvicorn"* ]]; then
    printf 'API'
  elif [[ "$command_line" == *"src/main.ts"* ]]; then
    printf 'Agent'
  else
    printf 'Backend supervisor'
  fi
}

# Match by executable working directory and a service-specific command. This
# deliberately avoids broad patterns such as `pkill -f uvicorn` or `killall
# python`, which could terminate another project on the same machine.
while read -r pid _ppid _pgid command_line; do
  [[ "$pid" =~ ^[0-9]+$ ]] || continue
  process_cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  case "$process_cwd" in
    "$FRONTEND_ROOT")
      if is_frontend_process "$command_line"; then add_candidate "$pid"; fi
      ;;
    "$BACKEND_ROOT"|"$BACKEND_ROOT/agent")
      if is_backend_process "$command_line"; then add_candidate "$pid"; fi
      ;;
  esac
done < <(ps -eo pid=,ppid=,pgid=,args=)

# Include PID files produced by the native launcher, but validate their cwd and
# command before using them so a stale/reused PID cannot kill an unrelated task.
for pid_file in "$PROJECT_ROOT/runtime-data/native/api.pid" \
                "$PROJECT_ROOT/runtime-data/native/agent.pid" \
                "$PROJECT_ROOT/runtime-data/native/web.pid"; do
  [[ -f "$pid_file" ]] || continue
  pid="$(<"$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ && -d "/proc/$pid" ]] || continue
  process_cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  process_command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  if [[ "$process_cwd" == "$FRONTEND_ROOT" ]] && is_frontend_process "$process_command"; then
    add_candidate "$pid"
  elif [[ "$process_cwd" == "$BACKEND_ROOT" || "$process_cwd" == "$BACKEND_ROOT/agent" ]] \
    && is_backend_process "$process_command"; then
    add_candidate "$pid"
  fi
done

if (( ${#CANDIDATES[@]} == 0 )); then
  printf '[AdCraft] 未发现由当前项目路径启动的 API、Agent 或 Web 进程。\n'
else
  mapfile -t pids < <(printf '%s\n' "${!CANDIDATES[@]}" | sort -rn)
  if (( DRY_RUN == 1 )); then
    printf '[AdCraft] 预览：会停止以下 %d 个当前项目进程；尚未发送信号。\n' "${#pids[@]}"
    for pid in "${pids[@]}"; do
      kill -0 "$pid" 2>/dev/null && printf '[AdCraft] %s PID %s\n' "$(process_label "$pid")" "$pid"
    done
    exit 0
  fi
  printf '[AdCraft] 将停止 %d 个当前项目进程（API %s、Agent %s、Web %s）。\n' \
    "${#pids[@]}" "$API_PORT" "$AGENT_PORT" "$WEB_PORT"
  for pid in "${pids[@]}"; do
    command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    [[ -n "$command_line" ]] || continue
    printf '[AdCraft] 停止 %s（PID %s）……\n' "$(process_label "$pid")" "$pid"
    kill -TERM "$pid" 2>/dev/null || true
  done

  deadline=$((SECONDS + 15))
  while (( SECONDS < deadline )); do
    still_running=0
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        still_running=1
        break
      fi
    done
    (( still_running == 0 )) && break
    sleep 1
  done

  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      printf '[AdCraft] PID %s 未在 15 秒内退出，发送 KILL。\n' "$pid"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
fi

if (( DRY_RUN == 1 )); then
  printf '[AdCraft] 预览完成；没有发现需要停止的当前项目进程。\n'
  exit 0
fi

for pid_file in "$PROJECT_ROOT/runtime-data/native/api.pid" \
                "$PROJECT_ROOT/runtime-data/native/agent.pid" \
                "$PROJECT_ROOT/runtime-data/native/web.pid"; do
  [[ -f "$pid_file" ]] || continue
  pid="$(<"$pid_file")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f -- "$pid_file"
  fi
done

port_is_listening() {
  local port="$1"
  local hex_port
  printf -v hex_port '%04X' "$port"
  awk -v wanted=":$hex_port" '
    NR > 1 && ($2 ~ wanted || $2 ~ ("\\]" wanted)) && $4 == "0A" { found = 1 }
    END { exit found ? 0 : 1 }
  ' /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

remaining=0
for entry in "API:$API_PORT" "Agent:$AGENT_PORT" "Web:$WEB_PORT"; do
  name="${entry%%:*}"
  port="${entry##*:}"
  if port_is_listening "$port"; then
    printf '[AdCraft] 警告：%s 端口 %s 仍有监听进程；该进程不符合当前项目路径，已保留。\n' "$name" "$port"
    remaining=1
  else
    printf '[AdCraft] %s 端口 %s 已释放。\n' "$name" "$port"
  fi
done

if (( remaining == 0 )); then
  printf '[AdCraft] AdCraft API、Agent 和 Web 已全部关闭（保留 .env、runtime-data 和日志）。\n'
else
  printf '[AdCraft] AdCraft 进程已停止；仍被其他项目占用的端口未被强制处理。\n'
  exit 1
fi
