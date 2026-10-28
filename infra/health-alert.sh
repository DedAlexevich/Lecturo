#!/usr/bin/env bash
set -euo pipefail

failures_to_alert=3
backup_max_age_hours=26
disk_max_percent=85
memory_max_percent=90
queue_stalled_minutes=60

cd "$(dirname "$0")/.."

source infra/env.sh

alert() {
  infra/alert.sh "$@"
}

db_query() {
  docker compose exec -T db psql -U lecturo -d lecturo -v ON_ERROR_STOP=1 -qAt -c "$1"
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
  if [ -f "$backup_alerted_file" ] && alert backup stale resolved "Бэкап Lecturo снова свежий: $fresh_backup"; then
    rm -f "$backup_alerted_file"
  fi
elif [ ! -f "$backup_alerted_file" ]; then
  if alert backup stale firing "Бэкап Lecturo устарел: в $backup_dir нет дампа моложе $backup_max_age_hours часов"; then
    touch "$backup_alerted_file"
  fi
fi

data_dir=$(env_value DATA_DIR ./data)
disk_alerted_file="$state_dir/disk-alerted"
disk_usage=$(df -P / "$data_dir" "$backup_dir" 2>/dev/null | awk -v max="$disk_max_percent" 'NR > 1 && !seen[$1]++ { used = $5 + 0; if (used >= max) print $6 ": " $5 }' || true)
if [ -z "$disk_usage" ]; then
  if [ -f "$disk_alerted_file" ] && alert disk_low disk resolved "Место на диске Lecturo снова есть: занято меньше $disk_max_percent%"; then
    rm -f "$disk_alerted_file"
  fi
elif [ ! -f "$disk_alerted_file" ]; then
  if alert disk_low disk firing "$(printf 'На сервере Lecturo кончается место, занято от %s%%:\n%s' "$disk_max_percent" "$disk_usage")"; then
    touch "$disk_alerted_file"
  fi
fi

memory_alerted_file="$state_dir/memory-alerted"
memory_used=$(awk '/^MemTotal:/ { total = $2 } /^MemAvailable:/ { available = $2 } END { if (total > 0) printf "%d", (total - available) * 100 / total }' /proc/meminfo 2>/dev/null || true)
if [ -n "$memory_used" ] && [ "$memory_used" -lt "$memory_max_percent" ]; then
  if [ -f "$memory_alerted_file" ] && alert memory_low memory resolved "Память на сервере Lecturo освободилась: занято $memory_used%"; then
    rm -f "$memory_alerted_file"
  fi
elif [ -n "$memory_used" ] && [ ! -f "$memory_alerted_file" ]; then
  top=$(ps -eo rss=,comm= --sort=-rss 2>/dev/null | head -n 5 | awk '{ printf "%s: %d МБ\n", $2, $1 / 1024 }' || true)
  if alert memory_low memory firing "$(printf 'На сервере Lecturo кончается память, занято %s%%\n\n%s' "$memory_used" "$top")"; then
    touch "$memory_alerted_file"
  fi
fi

queue_alerted_file="$state_dir/queue-alerted"
stalled=$(db_query "SELECT count(*) FROM lectures WHERE status = 'queued' AND updated_at < now() - interval '$queue_stalled_minutes minutes' AND NOT EXISTS (SELECT 1 FROM processing_steps WHERE started_at > now() - interval '$queue_stalled_minutes minutes' OR finished_at > now() - interval '$queue_stalled_minutes minutes' OR (status = 'running' AND started_at > now() - interval '4 hours'))" 2>/dev/null || true)
if [ "$stalled" = "0" ]; then
  if [ -f "$queue_alerted_file" ] && alert queue_stalled lectures resolved "Очередь обработки Lecturo снова разбирается"; then
    rm -f "$queue_alerted_file"
  fi
elif [ -n "$stalled" ] && [ ! -f "$queue_alerted_file" ]; then
  if alert queue_stalled lectures firing "Очередь обработки Lecturo стоит: лекций в очереди дольше $queue_stalled_minutes мин: $stalled, воркер ничего не обрабатывает"; then
    touch "$queue_alerted_file"
  fi
fi

public_url=$(env_value PUBLIC_URL)
url="${public_url:-http://localhost}/api/v1/health"
failures=$(cat "$failures_file" 2>/dev/null || echo 0)

problems=$(service_problems)
if curl -fsS -m 10 -o /dev/null "$url" && [ -z "$problems" ]; then
  echo 0 > "$failures_file"
  if [ -f "$alerted_file" ] && alert service_down health resolved "Lecturo снова работает: $url отвечает"; then
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
  if alert service_down health firing "$(printf 'Lecturo не отвечает: %s, проверок подряд: %s\n\n%s\n\n%s' "$url" "$failures" "${problems:-сервисы в порядке}" "$services")"; then
    touch "$alerted_file"
  fi
fi
exit 1
