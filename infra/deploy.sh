#!/usr/bin/env bash
set -euo pipefail

env_keys() {
  sed -n 's/^\([A-Z0-9_]*\)=.*/\1/p' "$1" | sort -u
}

warn_missing_env() {
  local missing
  missing=$(comm -23 <(env_keys .env.example) <(env_keys .env) | paste -sd ' ')
  if [ -n "$missing" ]; then
    echo "warning: keys from .env.example are missing in .env: $missing" >&2
  fi
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

  local previous previous_revision
  previous=$(git rev-parse HEAD)
  previous_revision=$(docker compose exec -T api alembic current 2>/dev/null | awk 'NR==1 {print $1}' || true)
  git reset --quiet --hard "$target"
  warn_missing_env
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
