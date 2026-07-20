#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/linux-common.sh
source "$SCRIPT_DIR/lib/linux-common.sh"

OS_ID=""
OS_CODENAME=""

as_root() {
  local failure_message="$1"
  shift

  if (( EUID == 0 )); then
    "$@" || {
      printf '[AdCraft] ERROR: %s\n' "$failure_message" >&2
      return 1
    }
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@" || {
      printf '[AdCraft] ERROR: %s\n' "$failure_message" >&2
      return 1
    }
  else
    printf '[AdCraft] ERROR: %s\n' "$failure_message" >&2
    return 1
  fi
}

detect_supported_os() {
  [[ -r /etc/os-release ]] || die "无法读取 /etc/os-release。"
  # shellcheck disable=SC1091
  source /etc/os-release
  case "${ID:-}" in
    ubuntu|debian)
      OS_ID="$ID"
      OS_CODENAME="${VERSION_CODENAME:-}"
      ;;
    *)
      die "第一版只支持 Ubuntu/Debian，当前系统为 ${ID:-unknown}。"
      ;;
  esac
  [[ -n "$OS_CODENAME" ]] || die "无法确定系统版本代号 VERSION_CODENAME。"
}

configure_docker_repository() (
  set -Eeuo pipefail
  local arch key_tmp source_tmp
  arch="$(dpkg --print-architecture)"
  key_tmp="$(mktemp)"
  source_tmp="$(mktemp)"
  trap 'rm -f "$key_tmp" "$source_tmp"' EXIT

  curl -fsSL "https://download.docker.com/linux/$OS_ID/gpg" -o "$key_tmp"
  cat > "$source_tmp" <<EOF
Types: deb
URIs: https://download.docker.com/linux/$OS_ID
Suites: $OS_CODENAME
Components: stable
Architectures: $arch
Signed-By: /etc/apt/keyrings/docker.asc
EOF

  as_root "无法创建 Docker APT 密钥目录。" install -m 0755 -d /etc/apt/keyrings
  as_root "无法安装 Docker APT 签名密钥。" install -m 0644 "$key_tmp" /etc/apt/keyrings/docker.asc
  as_root "无法写入 Docker APT 软件源。" install -m 0644 "$source_tmp" /etc/apt/sources.list.d/docker.sources
)

install_docker_engine() {
  info "安装 Docker Engine 和 Compose 插件……"
  as_root "无法更新 APT 软件包索引以安装 Docker。" apt-get update
  as_root "无法安装 Docker 所需的 ca-certificates 和 curl。" apt-get install -y ca-certificates curl
  remove_conflicting_docker_packages
  configure_docker_repository
  as_root "无法更新 Docker 官方软件源的软件包索引。" apt-get update
  as_root "无法从 Docker 官方软件源安装 Docker Engine。" apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin
}

remove_conflicting_docker_packages() {
  info "移除与 Docker 官方 Engine 冲突的发行版软件包……"
  as_root "无法移除与 Docker 官方 Engine 冲突的软件包。" apt-get remove -y \
    docker.io \
    docker-compose \
    docker-compose-v2 \
    docker-doc \
    podman-docker \
    containerd \
    runc
}

start_docker_service() {
  if command -v systemctl >/dev/null 2>&1; then
    if as_root "无法通过 systemctl 启动 Docker 服务。" systemctl enable --now docker; then
      return 0
    fi
  fi
  if command -v service >/dev/null 2>&1; then
    if as_root "无法通过 service 启动 Docker 服务。" service docker start; then
      return 0
    fi
  fi
  return 1
}

select_engine_cli() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    DOCKER=(docker)
  elif command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
  else
    return 1
  fi
}

ensure_docker() {
  local install_engine=0

  if ! command -v docker >/dev/null 2>&1; then
    install_engine=1
  elif ! select_engine_cli; then
    info "现有 Docker CLI 未连接到可用 Engine，尝试启动服务……"
    if ! start_docker_service || ! select_engine_cli; then
      info "Docker Engine 仍不可用，改为安装 Docker 官方 Engine……"
      install_engine=1
    fi
  fi

  if (( install_engine )); then
    install_docker_engine
    if ! select_engine_cli; then
      info "启动 Docker 服务……"
      start_docker_service || die "Docker Engine 安装后无法启动；请检查 systemd/service 和 Docker 服务日志。"
      select_engine_cli || die "Docker 服务启动后仍不可用。"
    fi
  fi

  if ! "${DOCKER[@]}" compose version >/dev/null 2>&1; then
    info "现有 Docker 缺少 Compose v2，改为安装 Docker 官方 Engine 和 Compose 插件……"
    install_docker_engine
    if ! select_engine_cli; then
      info "启动 Docker 服务……"
      start_docker_service || die "Docker Engine 安装后无法启动；请检查 systemd/service 和 Docker 服务日志。"
      select_engine_cli || die "Docker 服务启动后仍不可用。"
    fi
  fi

  select_docker || die "Docker Compose v2 不可用。"
}

initialize_env_file() {
  local target="$1"
  local example="$2"
  local owner_uid="$3"
  local owner_gid="$4"
  local target_dir target_name temp_file

  if [[ -e "$target" || -L "$target" ]]; then
    secure_env_file "$target" "$owner_uid" "$owner_gid"
    info "保留已有 ${target#"$PROJECT_ROOT/"}。"
    return
  fi

  target_dir="$(dirname -- "$target")"
  target_name="${target##*/}"
  temp_file="$(mktemp "$target_dir/.${target_name}.XXXXXX")" \
    || die "无法为 ${target#"$PROJECT_ROOT/"} 创建临时文件。"
  if ! install -m 0600 "$example" "$temp_file"; then
    rm -f "$temp_file"
    die "无法从示例初始化 ${target#"$PROJECT_ROOT/"}。"
  fi

  if ln "$temp_file" "$target" 2>/dev/null; then
    rm -f "$temp_file"
  elif [[ -e "$target" || -L "$target" ]]; then
    rm -f "$temp_file"
    secure_env_file "$target" "$owner_uid" "$owner_gid"
    info "保留并发创建的 ${target#"$PROJECT_ROOT/"}。"
    return
  else
    rm -f "$temp_file"
    die "无法发布 ${target#"$PROJECT_ROOT/"}。"
  fi

  secure_env_file "$target" "$owner_uid" "$owner_gid"
  info "已从示例创建 ${target#"$PROJECT_ROOT/"}。"
}

secure_env_file() {
  local target="$1"
  local owner_uid="$2"
  local owner_gid="$3"
  local mode current_uid current_gid

  [[ ! -L "$target" && -f "$target" ]] \
    || die "${target#"$PROJECT_ROOT/"} 已存在但不是普通文件。"
  current_uid="$(stat -c '%u' "$target")" \
    || die "无法读取 ${target#"$PROJECT_ROOT/"} 的所有者。"
  current_gid="$(stat -c '%g' "$target")" \
    || die "无法读取 ${target#"$PROJECT_ROOT/"} 的所属组。"
  if [[ "$current_uid" != "$owner_uid" || "$current_gid" != "$owner_gid" ]]; then
    as_root "无法将 ${target#"$PROJECT_ROOT/"} 交还给部署用户。" \
      chown "$owner_uid:$owner_gid" "$target" \
      || die "dotenv 所有权修复失败。"
  fi

  mode="$(stat -c '%a' "$target")" \
    || die "无法读取 ${target#"$PROJECT_ROOT/"} 的权限。"
  if [[ "$mode" != "600" ]]; then
    as_root "无法将 ${target#"$PROJECT_ROOT/"} 的权限设为 0600。" \
      chmod 600 "$target" \
      || die "dotenv 权限修复失败。"
  fi
}

prepare_api_source_directory() {
  local api_dir="$PROJECT_ROOT/apps/api"
  local deploy_uid="$1"
  local deploy_gid="$2"
  local current_uid current_gid

  [[ -d "$api_dir" && ! -L "$api_dir" ]] \
    || die "apps/api 必须是普通目录，不能是符号链接。"
  current_uid="$(stat -c '%u' "$api_dir")" \
    || die "无法读取 apps/api 的所有者。"
  current_gid="$(stat -c '%g' "$api_dir")" \
    || die "无法读取 apps/api 的所属组。"
  if [[ "$current_uid" != "$deploy_uid" || "$current_gid" != "$deploy_gid" ]]; then
    as_root "无法将 apps/api 目录交还给部署用户。" \
      chown "$deploy_uid:$deploy_gid" "$api_dir" \
      || die "apps/api 所有权修复失败。"
  fi
  as_root "无法为部署用户授予 apps/api 目录的写入和访问权限。" \
    chmod u+wx "$api_dir" \
    || die "apps/api 权限修复失败。"
}

prepare_runtime_directory() {
  local deploy_uid="$1"
  local deploy_gid="$2"
  local owner_uid owner_gid

  mkdir -p "$PROJECT_ROOT/runtime-data/api"
  owner_uid="$(stat -c '%u' "$PROJECT_ROOT/runtime-data/api")"
  owner_gid="$(stat -c '%g' "$PROJECT_ROOT/runtime-data/api")"
  if [[ "$owner_uid" != "$deploy_uid" || "$owner_gid" != "$deploy_gid" ]]; then
    as_root "无法将 runtime-data 交还给部署用户。" \
      chown -R "$deploy_uid:$deploy_gid" "$PROJECT_ROOT/runtime-data"
  fi
  chmod 700 "$PROJECT_ROOT/runtime-data" "$PROJECT_ROOT/runtime-data/api"
}

deployment_owner() {
  printf '%s %s\n' "${SUDO_UID:-$(id -u)}" "${SUDO_GID:-$(id -g)}"
}

ensure_port_tool() {
  if command -v ss >/dev/null 2>&1; then
    return
  fi
  info "安装端口检测工具 iproute2……"
  as_root "无法更新 APT 软件包索引以安装 iproute2。" apt-get update
  as_root "无法安装端口检测工具 iproute2。" apt-get install -y iproute2
}

port_is_free() {
  local port="$1"
  [[ -z "$(ss -H -ltn "sport = :$port")" ]]
}

choose_port() {
  local saved_port="" port

  if [[ -f "$STATE_FILE" ]]; then
    read_state_file
    export ADCRAFT_PORT ADCRAFT_UID ADCRAFT_GID
    saved_port="$ADCRAFT_PORT"
    if [[ -n "$(compose ps -q web 2>/dev/null || true)" ]]; then
      printf '%s\n' "$saved_port"
      return
    fi
    if port_is_free "$saved_port"; then
      printf '%s\n' "$saved_port"
      return
    fi
  fi

  for port in $(seq 8080 8179); do
    if port_is_free "$port"; then
      printf '%s\n' "$port"
      return
    fi
  done
  die "8080–8179 均被占用，无法发布 AdCraft Web 端口。"
}

write_state() {
  local port="$1" deploy_uid="$2" deploy_gid="$3" temp_file
  temp_file="$(mktemp "$PROJECT_ROOT/runtime-data/.deployment.env.XXXXXX")"
  chmod 600 "$temp_file"
  printf 'ADCRAFT_PORT=%s\nADCRAFT_UID=%s\nADCRAFT_GID=%s\n' \
    "$port" "$deploy_uid" "$deploy_gid" > "$temp_file"
  mv "$temp_file" "$STATE_FILE"
  if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
    as_root "无法将 deployment.env 交还给原始用户。" \
      chown "$deploy_uid:$deploy_gid" "$STATE_FILE"
  fi
}

open_browser_if_available() {
  local url="$1"
  if command -v xdg-open >/dev/null 2>&1 \
    && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    xdg-open "$url" >/dev/null 2>&1 &
  fi
}

main() {
  local ids deploy_uid deploy_gid port url

  validate_project
  detect_supported_os
  ensure_docker

  ids="$(deployment_owner)"
  read -r deploy_uid deploy_gid <<< "$ids"

  prepare_api_source_directory "$deploy_uid" "$deploy_gid"
  initialize_env_file \
    "$PROJECT_ROOT/apps/api/.env" \
    "$PROJECT_ROOT/apps/api/.env.example" \
    "$deploy_uid" \
    "$deploy_gid"
  initialize_env_file \
    "$PROJECT_ROOT/apps/web/.env" \
    "$PROJECT_ROOT/apps/web/.env.example" \
    "$deploy_uid" \
    "$deploy_gid"

  prepare_runtime_directory "$deploy_uid" "$deploy_gid"
  ensure_port_tool
  port="$(choose_port)"
  write_state "$port" "$deploy_uid" "$deploy_gid"
  load_state

  info "校验 Docker Compose 配置……"
  compose config --quiet

  info "构建 AdCraft 镜像……"
  compose build

  info "启动 AdCraft……"
  if ! compose up -d --remove-orphans; then
    show_recent_logs
    die "容器启动失败。"
  fi

  info "等待 Web/API 健康，最长 120 秒……"
  if ! wait_for_services; then
    show_recent_logs
    die "服务未在 120 秒内达到健康状态。"
  fi

  url="$(adcraft_url)"
  info "部署成功：$url"
  open_browser_if_available "$url"
}

main "$@"
