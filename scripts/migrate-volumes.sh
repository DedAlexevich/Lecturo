#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

project="${COMPOSE_PROJECT_NAME:-lecturo}"
image="${MIGRATE_IMAGE:-alpine:3}"
data_dir="${DATA_DIR:-}"
if [ -z "$data_dir" ] && [ -f .env ]; then
  data_dir=$(sed -n 's/^DATA_DIR=//p' .env | tail -n 1 | tr -d '\"\r')
fi
data_dir="${data_dir:-./data}"
mkdir -p "$data_dir"
data_dir=$(cd "$data_dir" && pwd)

pairs=(
  "pgdata:postgres"
  "storage:storage"
  "botredisdata:bot-redis"
  "caddy_data:caddy"
)

fail() {
  echo "error: $*" >&2
  exit 1
}

summarize() {
  docker run --rm -v "$1:/d:ro" "$image" sh -c \
    'cd /d && echo "$(find . | wc -l) $(find . -type f -exec stat -c %s {} + | awk "{s+=\$1} END {print s+0}")"'
}

migrate() {
  local volume=$1 target=$2
  if ! docker volume inspect "$volume" >/dev/null 2>&1; then
    echo "skip $volume: volume not found"
    return
  fi
  if [ -n "$(docker ps -q --filter "volume=$volume")" ]; then
    fail "volume $volume is used by a running container, run docker compose down first"
  fi
  mkdir -p "$target"
  if [ -n "$(docker run --rm -v "$target:/d:ro" "$image" ls -A /d)" ]; then
    fail "$target is not empty, move it away or remove it before migrating $volume"
  fi
  echo "copy $volume -> $target"
  docker run --rm -v "$volume:/from:ro" -v "$target:/to" "$image" cp -a /from/. /to/
  local before after
  before=$(summarize "$volume")
  after=$(summarize "$target")
  if [ "$before" != "$after" ]; then
    fail "check failed for $volume: volume has '$before' (entries, bytes), folder has '$after'"
  fi
  echo "ok $volume: ${before% *} entries, ${before#* } bytes"
}

for pair in "${pairs[@]}"; do
  migrate "${project}_${pair%%:*}" "$data_dir/${pair#*:}"
done

echo "done, old volumes are kept"
