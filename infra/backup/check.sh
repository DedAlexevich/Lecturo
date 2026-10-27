#!/usr/bin/env bash
set -euo pipefail

file="${1:+$(realpath -m "$1")}"

source "$(dirname "$0")/common.sh"

file="${file:-$(latest_backup "$backup_dir")}"
[ -n "$file" ] || fail "no backups in $backup_dir"
[ -f "$file" ] || fail "$file not found"

if [ -n "$db_container" ]; then
  image=$(docker inspect -f '{{.Config.Image}}' "$db_container")
else
  image=$(docker compose config --images "$db_service")
fi
container="${BACKUP_CHECK_CONTAINER:-lecturo-backup-check}"

docker rm -f "$container" > /dev/null 2>&1 || true
docker run -d --rm --name "$container" --network none \
  -e POSTGRES_USER=lecturo -e POSTGRES_DB=lecturo -e POSTGRES_HOST_AUTH_METHOD=trust \
  "$image" > /dev/null
trap 'docker rm -f "$container" > /dev/null 2>&1 || true' EXIT

for _ in $(seq 60); do
  docker exec "$container" pg_isready -q -h 127.0.0.1 -U lecturo && break
  sleep 1
done
docker exec "$container" pg_isready -q -h 127.0.0.1 -U lecturo || fail "postgres in $container did not start"

docker exec -i "$container" pg_restore -U lecturo -d lecturo --no-owner --exit-on-error < "$file"

query() {
  docker exec "$container" psql -U lecturo -d lecturo -Atc "$1"
}

revision=$(query "select version_num from alembic_version")
[ -n "$revision" ] || fail "alembic_version is empty in $file"
tables=$(query "select count(*) from information_schema.tables where table_schema = 'public'")
users=$(query "select count(*) from users")

echo "ok $file: revision $revision, $tables tables, $users users"
