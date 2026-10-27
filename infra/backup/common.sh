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
db_service=$(env_value BACKUP_DB_SERVICE db)
db_container=$(env_value BACKUP_DB_CONTAINER "")

db_exec() {
  if [ -n "$db_container" ]; then
    docker exec -i "$db_container" "$@"
  else
    docker compose exec -T "$db_service" "$@"
  fi
}

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
  if ! db_exec sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$part"; then
    rm -f "$part"
    fail "pg_dump failed"
  fi
  if ! db_exec pg_restore --list < "$part" > /dev/null; then
    rm -f "$part"
    fail "dump is not readable by pg_restore"
  fi
  mv "$part" "$target"
  echo "saved $target ($(du -h "$target" | cut -f1))"
}

rotate_backups() {
  local dir=$1 keep=$2
  local old file
  mapfile -t old < <(printf '%s\n' "$dir"/lecturo-*.dump | sort -r | tail -n +$((keep + 1)))
  for file in "${old[@]}"; do
    [ -e "$file" ] || continue
    rm -f "$file"
    echo "removed $file"
  done
}

restore_database() {
  local file=$1
  db_exec sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' || return 1
  db_exec sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' < "$file"
}

latest_backup() {
  local dir=$1
  local files=("$dir"/lecturo-*.dump)
  [ -e "${files[0]}" ] || return 0
  printf '%s\n' "${files[@]}" | sort | tail -n 1
}
