#!/usr/bin/env bash

set -Eeuo pipefail

COMMON_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$COMMON_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/compose.yaml"
STATE_FILE="$PROJECT_ROOT/runtime-data/deployment.env"
DOCKER=()

info() {
  printf '[AdCraft] %s\n' "$*"
}

die() {
  printf '[AdCraft] ERROR: %s\n' "$*" >&2
  exit 1
}

validate_project() {
  [[ -f "$COMPOSE_FILE" ]] || die "未找到 $COMPOSE_FILE，请从完整的 AdCraft 项目中运行脚本。"
  [[ -f "$PROJECT_ROOT/apps/api/.env.example" ]] || die "缺少 apps/api/.env.example。"
  [[ -f "$PROJECT_ROOT/apps/web/.env.example" ]] || die "缺少 apps/web/.env.example。"
}

load_state() {
  [[ -f "$STATE_FILE" ]] || die "缺少 $STATE_FILE，请先运行 scripts/deploy-linux.sh。"
  read_state_file
  export ADCRAFT_PORT ADCRAFT_UID ADCRAFT_GID ADCRAFT_AGENT_RUNTIME_TOKEN
}

read_state_file() {
  local allow_missing_agent_token="${1:-false}"
  local line key value seen_port=0 seen_uid=0 seen_gid=0 seen_agent_token=0
  ADCRAFT_PORT=""
  ADCRAFT_UID=""
  ADCRAFT_GID=""
  ADCRAFT_AGENT_RUNTIME_TOKEN=""

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^([A-Z_]+)=(.*)$ ]] || die "deployment.env 格式无效。"
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      ADCRAFT_PORT)
        [[ "$value" =~ ^[0-9]+$ ]] || die "deployment.env 格式无效。"
        (( seen_port == 0 )) || die "deployment.env 包含重复端口。"
        printf -v ADCRAFT_PORT '%s' "$value"
        seen_port=1
        ;;
      ADCRAFT_UID)
        [[ "$value" =~ ^[0-9]+$ ]] || die "deployment.env 格式无效。"
        (( seen_uid == 0 )) || die "deployment.env 包含重复 UID。"
        printf -v ADCRAFT_UID '%s' "$value"
        seen_uid=1
        ;;
      ADCRAFT_GID)
        [[ "$value" =~ ^[0-9]+$ ]] || die "deployment.env 格式无效。"
        (( seen_gid == 0 )) || die "deployment.env 包含重复 GID。"
        printf -v ADCRAFT_GID '%s' "$value"
        seen_gid=1
        ;;
      ADCRAFT_AGENT_RUNTIME_TOKEN)
        [[ "$value" =~ ^[0-9a-f]{64}$ ]] || die "deployment.env 中的 Agent 内部令牌无效。"
        (( seen_agent_token == 0 )) || die "deployment.env 包含重复 Agent 内部令牌。"
        printf -v ADCRAFT_AGENT_RUNTIME_TOKEN '%s' "$value"
        seen_agent_token=1
        ;;
      *) die "deployment.env 包含未知字段。" ;;
    esac
  done < "$STATE_FILE"

  (( seen_port && seen_uid && seen_gid )) || die "deployment.env 缺少字段。"
  if [[ "$allow_missing_agent_token" != true ]]; then
    (( seen_agent_token )) || die "deployment.env 缺少 Agent 内部令牌；请重新运行 scripts/deploy-linux.sh。"
  fi
  (( 10#$ADCRAFT_PORT >= 8080 && 10#$ADCRAFT_PORT <= 8179 )) || die "deployment.env 端口超出范围。"
}

select_docker() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    DOCKER=(docker)
  elif command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
  else
    return 1
  fi
  "${DOCKER[@]}" compose version >/dev/null 2>&1
}

compose() {
  "${DOCKER[@]}" compose \
    --env-file "$STATE_FILE" \
    -f "$COMPOSE_FILE" \
    "$@"
}

container_health() {
  local service="$1"
  local container_id
  container_id="$(compose ps -q "$service")"
  if [[ -z "$container_id" ]]; then
    printf 'missing\n'
    return
  fi
  "${DOCKER[@]}" inspect \
    --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "$container_id"
}

wait_for_services() {
  local timeout_seconds="${ADCRAFT_DEPLOY_WAIT_SECONDS:-1800}"
  [[ "$timeout_seconds" =~ ^[0-9]+$ ]] && (( 10#$timeout_seconds >= 120 )) \
    || die "ADCRAFT_DEPLOY_WAIT_SECONDS 必须是至少 120 的整数。"
  local deadline=$((SECONDS + 10#$timeout_seconds))
  local agent_status api_status web_status elapsed
  local -a frames=('|' '/' '-' '\\')
  local frame_index=0
  while (( SECONDS < deadline )); do
    agent_status="$(container_health agent)"
    api_status="$(container_health api)"
    web_status="$(container_health web)"
    if [[ "$agent_status" == healthy && "$api_status" == healthy && "$web_status" == healthy ]]; then
      printf '\r[AdCraft] Agent/API/Web 已全部健康。%60s\n' ''
      return 0
    fi
    if [[ "$agent_status" =~ ^(exited|dead)$ || "$api_status" =~ ^(exited|dead)$ || "$web_status" =~ ^(exited|dead)$ ]]; then
      printf '\n' >&2
      return 1
    fi
    elapsed=$((SECONDS - (deadline - 10#$timeout_seconds)))
    printf '\r[AdCraft] 等待服务 %s %4ds/%ds（agent=%s api=%s web=%s）' \
      "${frames[$frame_index]}" "$elapsed" "$timeout_seconds" \
      "$agent_status" "$api_status" "$web_status"
    frame_index=$(( (frame_index + 1) % ${#frames[@]} ))
    sleep 2
  done
  printf '\n' >&2
  return 1
}

show_recent_logs() {
  compose logs --tail=100 agent api web >&2 || true
}

adcraft_url() {
  printf 'http://127.0.0.1:%s\n' "$ADCRAFT_PORT"
}
