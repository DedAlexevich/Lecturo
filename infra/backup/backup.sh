#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

check_keep "$backup_keep"
wait_for_deploy
name="lecturo-$(date -u +%Y%m%d-%H%M%S)"
dump="$backup_dir/$name.dump"
dump_database "$dump"

if [ -z "$age_recipient" ]; then
  infra/backup/check.sh "$dump"
  rotate_backups "$backup_dir" "$backup_keep"
  warn "BACKUP_AGE_RECIPIENT is not set, $dump is not encrypted and not uploaded"
  exit 0
fi

stage=$(new_stage)
trap 'rm -rf "$stage"' EXIT
mv "$dump" "$stage/lecturo.dump"
infra/backup/check.sh "$stage/lecturo.dump"
dkim_saved=yes
save_dkim "$stage/dkim.tar" || dkim_saved=no
archive="$backup_dir/$name.tar.age"
seal_backup "$stage" "$archive"
rotate_backups "$backup_dir" "$backup_keep"
upload_backup "$archive"
[ "$dkim_saved" = yes ] || fail "$archive is saved without DKIM keys"
