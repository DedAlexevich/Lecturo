#!/usr/bin/env bash
set -euo pipefail

failures_to_alert=3
backup_max_age_hours=26

cd "$(dirname "$0")/.."

env_value() {
  grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

notify() {
  infra/notify.sh "$1"
}

service_problems() {
  local states service
  states=$(docker compose ps --all --format '{{.Service}}\t{{.State}}\t{{.Health}}\t{{.ExitCode}}' 2>&1) || {
    echo "docker compose ps: $states"
    return
  }
  while read -r service; do
    grep -q "^$service"$'\t' <<<"$states" || echo "$service: no container"
  done < <(docker compose config --services)
  awk -F '\t' '
    $1 == "migrate" && $2 == "exited" && $4 == "0" { next }
    $2 != "running" || ($3 != "" && $3 != "healthy") { print $1 ": " $2 " " $3 }
  ' <<<"$states"
}

exec 9<.git
if ! flock -n 9; then
  echo "deploy in progress, skipping"
  exit 0
fi

state_dir=${STATE_DIRECTORY:-${XDG_STATE_HOME:-$HOME/.local/state}/lecturo}
mkdir -p "$state_dir"
failures_file="$state_dir/health-failures"
alerted_file="$state_dir/health-alerted"

backup_dir=$(env_value BACKUP_DIR)
backup_dir=${backup_dir:-./backups}
backup_alerted_file="$state_dir/backup-alerted"
fresh_backup=$(find "$backup_dir" -maxdepth 1 \( -name 'lecturo-*.dump' -o -name 'lecturo-*.tar.age' \) -mmin -$((backup_max_age_hours * 60)) -print -quit 2>/dev/null || true)
if [ -n "$fresh_backup" ]; then
  if [ -f "$backup_alerted_file" ] && notify "Бэкап Lecturo снова свежий: $fresh_backup"; then
    rm -f "$backup_alerted_file"
  fi
elif [ ! -f "$backup_alerted_file" ]; then
  if notify "Бэкап Lecturo устарел: в $backup_dir нет дампа моложе $backup_max_age_hours часов"; then
    touch "$backup_alerted_file"
  fi
fi

public_url=$(env_value PUBLIC_URL)
url="${public_url:-http://localhost}/api/v1/health"
failures=$(cat "$failures_file" 2>/dev/null || echo 0)

problems=$(service_problems)
if curl -fsS -m 10 -o /dev/null "$url" && [ -z "$problems" ]; then
  echo 0 > "$failures_file"
  if [ -f "$alerted_file" ] && notify "Lecturo снова работает: $url отвечает"; then
    rm -f "$alerted_file"
  fi
  exit 0
fi

failures=$((failures + 1))
echo "$failures" > "$failures_file"
echo "health check failed $failures time(s) in a row"
[ -z "$problems" ] || printf '%s\n' "$problems"

if [ "$failures" -ge "$failures_to_alert" ] && [ ! -f "$alerted_file" ]; then
  services=$(docker compose ps --all --format '{{.Service}}: {{.Status}}' 2>&1 || true)
  if notify "$(printf 'Lecturo не отвечает: %s, проверок подряд: %s\n\n%s\n\n%s' "$url" "$failures" "${problems:-сервисы в порядке}" "$services")"; then
    touch "$alerted_file"
  fi
fi
exit 1
