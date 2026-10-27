#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/local-backup-env.sh"
exec infra/backup/backup.sh "$@"
