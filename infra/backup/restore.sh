#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: restore.sh <backup.dump>" >&2
  exit 1
fi
file=$(realpath -m "$1")

source "$(dirname "$0")/common.sh"

[ -f "$file" ] || fail "$file not found"

echo "database lecturo will be replaced with $file"
read -r -p "type yes to continue: " answer
[ "$answer" = yes ] || fail "cancelled"

wait_for_deploy
safety="$backup_dir/pre-restore-$(date -u +%Y%m%d-%H%M%S).dump"
dump_database "$safety"

docker compose stop api worker bot
if ! restore_database "$file"; then
  fail "restore failed, services are stopped, previous database is saved in $safety"
fi

docker compose up -d --wait --wait-timeout 300 api worker bot
echo "restored $file, previous database is saved in $safety"
