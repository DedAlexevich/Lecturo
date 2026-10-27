#!/usr/bin/env bash
set -euo pipefail

main() {
  local target="${1:-origin/main}"
  cd "$(dirname "$0")/.."

  git fetch --quiet origin main
  local previous previous_revision
  previous=$(git rev-parse HEAD)
  previous_revision=$(docker compose exec -T api alembic current 2>/dev/null | awk 'NR==1 {print $1}' || true)
  git reset --quiet --hard "$target"
  echo "deploying $(git rev-parse --short HEAD), previous $(git rev-parse --short "$previous") at revision ${previous_revision:-none}"

  if ! docker compose up -d --build --remove-orphans --wait --wait-timeout 300; then
    docker compose logs --tail 100 api worker
    echo "deploy failed, rolling back to $previous" >&2
    if [ -n "$previous_revision" ]; then
      docker compose run --rm --no-deps api alembic downgrade "$previous_revision"
    fi
    git reset --quiet --hard "$previous"
    docker compose up -d --build --remove-orphans --wait --wait-timeout 300
    exit 1
  fi

  docker image prune -f >/dev/null
}

main "$@"
exit
