#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/linux-common.sh"

validate_project
load_state
select_docker || die "Docker Compose v2 不可用。"
compose logs --tail=100 api web
