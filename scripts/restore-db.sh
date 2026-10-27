#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: restore-db.sh <backup.dump>" >&2
  exit 1
fi
file=$(realpath -m "$1")

source "$(dirname "$0")/local-backup-env.sh"
exec infra/backup/restore.sh "$file"
