#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

env_value() {
  grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

token=$(env_value TELEGRAM_BOT_TOKEN)
chat_id=$(env_value ALERT_TELEGRAM_CHAT_ID)
api_ip=$(env_value TELEGRAM_API_IP)
if [ -z "$token" ] || [ -z "$chat_id" ]; then
  echo "TELEGRAM_BOT_TOKEN or ALERT_TELEGRAM_CHAT_ID is not set, alert not sent: $1" >&2
  exit 1
fi
printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" |
  curl -fsS -m 15 -o /dev/null -K - --resolve "api.telegram.org:443:${api_ip:-149.154.167.220}" --data-urlencode "chat_id=$chat_id" --data-urlencode "text=$1"
