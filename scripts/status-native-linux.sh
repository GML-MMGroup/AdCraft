#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/native-linux-common.sh"

native_validate_project
native_load_state
native_remove_stale_pid_file "$NATIVE_API_PID_FILE"
native_remove_stale_pid_file "$NATIVE_WEB_PID_FILE"

if native_pid_is_running "$NATIVE_API_PID_FILE"; then
  printf '[AdCraft] API: running (PID %s)\n' "$(<"$NATIVE_API_PID_FILE")"
else
  printf '[AdCraft] API: stopped\n'
fi
if native_pid_is_running "$NATIVE_WEB_PID_FILE"; then
  printf '[AdCraft] Web: running (PID %s)\n' "$(<"$NATIVE_WEB_PID_FILE")"
else
  printf '[AdCraft] Web: stopped\n'
fi
if curl --fail --silent --max-time 3 "$(native_api_health_url)" >/dev/null 2>&1; then
  printf '[AdCraft] API health: healthy\n'
else
  printf '[AdCraft] API health: unavailable\n'
fi
if curl --fail --silent --max-time 3 "$(native_url)" >/dev/null 2>&1; then
  printf '[AdCraft] Web health: reachable\n'
else
  printf '[AdCraft] Web health: unavailable\n'
fi
printf '[AdCraft] URL: %s\n' "$(native_url)"
