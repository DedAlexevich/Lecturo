#!/usr/bin/env bash
set -euo pipefail

failures_to_alert=3

cd "$(dirname "$0")/.."

env_value() {
  grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2-
}

notify() {
  local token chat_id
  token=$(env_value TELEGRAM_BOT_TOKEN)
  chat_id=$(env_value ALERT_TELEGRAM_CHAT_ID)
  if [ -z "$token" ] || [ -z "$chat_id" ]; then
    echo "TELEGRAM_BOT_TOKEN or ALERT_TELEGRAM_CHAT_ID is not set, alert not sent: $1" >&2
    return 1
  fi
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" |
    curl -fsS -m 15 -o /dev/null -K - --data-urlencode "chat_id=$chat_id" --data-urlencode "text=$1"
}

exec 9<.git
if ! flock -n 9; then
  echo "deploy in progress, skipping"
  exit 0
fi
flock -u 9

state_dir=${STATE_DIRECTORY:-${XDG_STATE_HOME:-$HOME/.local/state}/lecturo}
mkdir -p "$state_dir"
failures_file="$state_dir/health-failures"
alerted_file="$state_dir/health-alerted"

public_url=$(env_value PUBLIC_URL)
url="${public_url:-http://localhost}/api/v1/health"
failures=$(cat "$failures_file" 2>/dev/null || echo 0)

if curl -fsS -m 10 -o /dev/null "$url"; then
  echo 0 > "$failures_file"
  if [ -f "$alerted_file" ] && notify "Lecturo снова работает: $url отвечает"; then
    rm -f "$alerted_file"
  fi
  exit 0
fi

failures=$((failures + 1))
echo "$failures" > "$failures_file"
echo "health check failed $failures time(s) in a row"

if [ "$failures" -ge "$failures_to_alert" ] && [ ! -f "$alerted_file" ]; then
  services=$(docker compose ps --all --format '{{.Service}}: {{.Status}}' 2>&1 || true)
  if notify "$(printf 'Lecturo не отвечает: %s, проверок подряд: %s\n\n%s' "$url" "$failures" "$services")"; then
    touch "$alerted_file"
  fi
fi
exit 1
