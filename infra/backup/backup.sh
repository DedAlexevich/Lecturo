#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

check_keep "$backup_keep"
if [ "${1:-}" != --no-wait ]; then
  wait_for_deploy
fi
dump_database "$backup_dir/lecturo-$(date -u +%Y%m%d-%H%M%S).dump"
rotate_backups "$backup_dir" "$backup_keep"
