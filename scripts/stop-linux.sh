#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/linux-common.sh"

validate_project
load_state
select_docker || die "Docker Compose v2 不可用。"
info "停止 AdCraft 容器（保留 .env、runtime-data、镜像和卷）……"
compose stop
info "AdCraft 已停止：$(adcraft_url)"
