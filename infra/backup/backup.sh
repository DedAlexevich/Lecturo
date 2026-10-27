#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

wait_for_deploy
dump_database "$backup_dir/lecturo-$(date -u +%Y%m%d-%H%M%S).dump"

mapfile -t old < <(printf '%s\n' "$backup_dir"/lecturo-*.dump | sort -r | tail -n +$((backup_keep + 1)))
for file in "${old[@]}"; do
  rm -f "$file"
  echo "removed $file"
done
