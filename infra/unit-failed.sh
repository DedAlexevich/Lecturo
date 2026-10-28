#!/usr/bin/env bash
set -euo pipefail

unit=$1
invocation=$(systemctl show -p InvocationID --value "$unit" 2>/dev/null || true)
if [ -n "$invocation" ]; then
  log=$(journalctl "_SYSTEMD_INVOCATION_ID=$invocation" -n 20 --no-pager -o cat 2>&1 | tail -c 3000 || true)
else
  log=$(journalctl -u "$unit" -n 20 --no-pager -o cat 2>&1 | tail -c 3000 || true)
fi
exec "$(dirname "$0")/notify.sh" "$(printf 'Lecturo: сбой %s на %s\n\n%s' "$unit" "$(hostname)" "$log")"
