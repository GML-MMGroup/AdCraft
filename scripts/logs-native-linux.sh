#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/native-linux-common.sh"

native_validate_project
native_load_state
[[ -f "$NATIVE_API_LOG_FILE" || -f "$NATIVE_WEB_LOG_FILE" ]] \
  || native_die "尚无原生日志，请先运行 scripts/deploy-native-linux.sh。"
tail -n 100 "$NATIVE_API_LOG_FILE" "$NATIVE_WEB_LOG_FILE"
