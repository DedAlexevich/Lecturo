#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: $0 <kind> <key> <firing|resolved|event> <text>" >&2
  exit 2
fi
kind=$1
key=$2
state=$3
text=$4

cd "$(dirname "$0")/.."

queue_signal() {
  docker compose ps --status running --services 2>/dev/null | grep -qx bot || return 1
  docker compose exec -T db psql -U lecturo -d lecturo -v ON_ERROR_STOP=1 -qAt \
    -v kind="$kind" -v key="$key" -v state="$state" -v text="$text" <<'SQL'
INSERT INTO admin_alert_signals (kind, key, state, text)
VALUES (:'kind', left(:'key', 128), :'state', :'text');
SELECT count(*) FROM users WHERE is_admin AND telegram_chat_id IS NOT NULL;
SQL
}

recipients=$(queue_signal 2>/dev/null || echo 0)
if [ "${recipients:-0}" -gt 0 ]; then
  exit 0
fi
exec infra/notify.sh "$text"
