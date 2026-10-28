#!/usr/bin/env bash
set -euo pipefail

unit=$1
log=$(journalctl -u "$unit" -n 20 --no-pager -o cat 2>&1 | tail -c 3000 || true)
exec "$(dirname "$0")/notify.sh" "$(printf 'Lecturo: сбой %s на %s\n\n%s' "$unit" "$(hostname)" "$log")"
