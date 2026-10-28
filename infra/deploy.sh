#!/usr/bin/env bash
set -euo pipefail

compose_up() {
  docker compose up -d --remove-orphans --wait --wait-timeout 300
}

alembic_revision() {
  docker compose run --rm --no-deps -T migrate alembic "$1" | awk '$1 ~ /^[0-9A-Za-z_]+$/ {print $1; exit}'
}

restore_code() {
  git reset --quiet --hard "$1"
  docker compose build || echo "rebuild of $(git rev-parse --short HEAD) failed" >&2
}

rollback() {
  local previous=$1 previous_revision=$2 dump=$3
  docker compose logs --tail 100 migrate api worker bot || true
  echo "deploy failed, rolling back to $previous" >&2
  if [ -n "$dump" ]; then
    echo "database dump before deploy: $dump" >&2
  fi
  if [ -n "$previous_revision" ]; then
    if ! docker compose run --rm --no-deps -T migrate alembic downgrade "$previous_revision"; then
      echo "alembic downgrade to $previous_revision failed, code stays at $(git rev-parse --short HEAD)" >&2
      exit 1
    fi
  fi
  restore_code "$previous"
  compose_up
  exit 1
}

main() {
  local target="${1:-origin/main}"
  cd "$(dirname "$0")/.."
  exec 9<.git
  if ! flock -n 9; then
    echo "waiting for another deploy"
    flock 9
  fi

  git fetch --quiet origin main
  if ! git merge-base --is-ancestor HEAD "$target"; then
    echo "$(git rev-parse --short "$target") is not newer than $(git rev-parse --short HEAD), skipping"
    exit 0
  fi

  local previous previous_revision new_head dump=""
  previous=$(git rev-parse HEAD)
  git reset --quiet --hard "$target"

  if ! docker compose build; then
    echo "build failed, code returned to $previous" >&2
    restore_code "$previous"
    exit 1
  fi

  previous_revision=""
  if [ -n "$(docker compose ps -q --status running db)" ] && ! previous_revision=$(alembic_revision current); then
    echo "cannot read current alembic revision, code returned to $previous" >&2
    restore_code "$previous"
    exit 1
  fi
  if ! new_head=$(alembic_revision heads) || [ -z "$new_head" ]; then
    echo "cannot read alembic heads, code returned to $previous" >&2
    restore_code "$previous"
    exit 1
  fi
  echo "deploying $(git rev-parse --short HEAD), previous $(git rev-parse --short "$previous") at revision ${previous_revision:-none}, new head $new_head"

  if [ -n "$previous_revision" ] && [ "$new_head" != "$previous_revision" ]; then
    local backup_log
    if ! backup_log=$(infra/backup/backup.sh --no-wait 2>&1); then
      echo "$backup_log" >&2
      echo "backup failed, code returned to $previous" >&2
      restore_code "$previous"
      exit 1
    fi
    echo "$backup_log"
    dump=$(sed -n 's/^\(saved\|encrypted\) \(.*\) (.*)$/\2/p' <<<"$backup_log" | tail -n 1)
    if [ -z "$dump" ]; then
      echo "backup path not found in backup output, code returned to $previous" >&2
      restore_code "$previous"
      exit 1
    fi
    echo "database saved to $dump before migration"
  fi

  if ! docker compose run --rm -T migrate; then
    rollback "$previous" "$previous_revision" "$dump"
  fi
  if ! compose_up; then
    rollback "$previous" "$previous_revision" "$dump"
  fi

  docker image prune -f >/dev/null
}

main "$@"
exit
