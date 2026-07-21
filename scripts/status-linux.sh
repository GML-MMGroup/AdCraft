#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/linux-common.sh"

validate_project
load_state
select_docker || die "Docker Compose v2 不可用。"
compose ps
printf '[AdCraft] URL: %s\n' "$(adcraft_url)"
printf '[AdCraft] API health: %s\n' "$(container_health api)"
printf '[AdCraft] Web health: %s\n' "$(container_health web)"
