cd "$(dirname "${BASH_SOURCE[0]}")/../.."

fail() {
  echo "error: $*" >&2
  exit 1
}

env_value() {
  local value="${!1:-}"
  if [ -z "$value" ] && [ -f .env ]; then
    value=$(sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '"\r')
  fi
  echo "${value:-$2}"
}

backup_dir=$(env_value BACKUP_DIR ./backups)
backup_keep=$(env_value BACKUP_KEEP 7)

wait_for_deploy() {
  exec 9<.git
  if ! flock -n 9; then
    echo "waiting for deploy to finish"
    flock 9
  fi
}

dump_database() {
  local target=$1
  local part
  part="$(dirname "$target")/.$(basename "$target").part"
  umask 077
  mkdir -p "$(dirname "$target")"
  if ! docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$part"; then
    rm -f "$part"
    fail "pg_dump failed"
  fi
  if ! docker compose exec -T db pg_restore --list < "$part" > /dev/null; then
    rm -f "$part"
    fail "dump is not readable by pg_restore"
  fi
  mv "$part" "$target"
  echo "saved $target ($(du -h "$target" | cut -f1))"
}

latest_backup() {
  local files=("$backup_dir"/lecturo-*.dump)
  [ -e "${files[0]}" ] || return 0
  printf '%s\n' "${files[@]}" | sort | tail -n 1
}
