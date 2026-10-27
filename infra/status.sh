#!/usr/bin/env bash
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

env_value() {
  grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

public_url=$(env_value PUBLIC_URL)
public_url=${public_url:-http://localhost}
data_dir=$(env_value DATA_DIR)
data_dir=${data_dir:-./data}

echo "== services"
docker compose ps --all --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'

echo
echo "== health $public_url/api/v1/health"
if health=$(curl -fsS -m 10 "$public_url/api/v1/health" 2>&1); then
  echo "$health"
else
  echo "FAILED: $health"
fi

echo
echo "== arq queue"
echo "queued: $(docker compose exec -T redis redis-cli zcard arq:queue)"
echo "in progress: $(docker compose exec -T redis redis-cli --scan --pattern 'arq:in-progress:*' | wc -l)"

echo
echo "== disk"
df -h / "$data_dir"
docker system df

echo
echo "== memory"
free -h

echo
echo "== errors in the last hour"
errors=$(docker compose logs --no-color --since 1h api worker bot 2>&1 | grep -E 'ERROR|CRITICAL|Traceback' | tail -n 20)
echo "${errors:-none}"
