#!/usr/bin/env bash
set -euo pipefail

main() {
  local target="${1:-origin/main}"
  cd "$(dirname "$0")/.."

  local previous
  previous=$(git rev-parse HEAD)
  git fetch --quiet origin main
  git reset --quiet --hard "$target"
  echo "deploying $(git rev-parse --short HEAD), previous $(git rev-parse --short "$previous")"

  if ! docker compose up -d --build --remove-orphans --wait --wait-timeout 300; then
    docker compose logs --tail 100 api worker
    echo "deploy failed, rolling back to $previous" >&2
    git reset --quiet --hard "$previous"
    docker compose up -d --build --remove-orphans --wait --wait-timeout 300
    exit 1
  fi

  docker image prune -f >/dev/null
}

main "$@"
exit
