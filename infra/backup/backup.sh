#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

wait_for_deploy
dump_database "$backup_dir/lecturo-$(date -u +%Y%m%d-%H%M%S).dump"
rotate_backups "$backup_dir" "$backup_keep"
