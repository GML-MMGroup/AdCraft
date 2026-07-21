#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/native-linux-common.sh"

native_validate_project
native_load_state
native_stop_process Web "$NATIVE_WEB_PID_FILE"
native_stop_process API "$NATIVE_API_PID_FILE"
native_info "原生 AdCraft 已停止（保留 .env、runtime-data 和日志）：$(native_url)"
