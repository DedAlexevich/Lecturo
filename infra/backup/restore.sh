#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: restore.sh <backup.dump | backup.tar.age>" >&2
  exit 1
fi
file=$(realpath -m "$1")

source "$(dirname "$0")/common.sh"

[ -f "$file" ] || fail "$file not found"

dump=$file
if [[ "$file" == *.tar.age ]]; then
  identity=$(env_value BACKUP_AGE_IDENTITY "")
  [ -n "$identity" ] || fail "set BACKUP_AGE_IDENTITY to the private key file to restore $file"
  umask 007
  mkdir -p "$backup_dir"
  work=$(mktemp -d "$backup_dir/.restore-XXXXXX")
  trap 'rm -rf "$work"' EXIT
  age -d -i "$identity" "$file" | tar -C "$work" -xf - lecturo.dump || fail "could not decrypt $file"
  dump="$work/lecturo.dump"
fi

echo "database lecturo will be replaced with $file"
read -r -p "type yes to continue: " answer
[ "$answer" = yes ] || fail "cancelled"

wait_for_deploy
safety="$backup_dir/pre-restore-$(date -u +%Y%m%d-%H%M%S).dump"
dump_database "$safety"
if [ -n "$age_recipient" ]; then
  stage=$(new_stage)
  mv "$safety" "$stage/lecturo.dump"
  safety="${safety%.dump}.tar.age"
  seal_backup "$stage" "$safety"
fi

docker compose stop api worker bot
if ! restore_database "$dump"; then
  fail "restore failed, services are stopped, previous database is saved in $safety"
fi

docker compose up -d --wait --wait-timeout 300 api worker bot
rotate_backups "$backup_dir" 3 pre-restore
echo "restored $file, previous database is saved in $safety"
