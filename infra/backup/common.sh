#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1

fail() {
  echo "error: $*" >&2
  exit 1
}

warn() {
  echo "warning: $*" >&2
}

source infra/env.sh

backup_dir=$(env_value BACKUP_DIR ./backups)
db_service=$(env_value BACKUP_DB_SERVICE db)
db_container=$(env_value BACKUP_DB_CONTAINER "")
age_recipient=$(env_value BACKUP_AGE_RECIPIENT "")

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
  rm -rf "$(dirname "$target")"/.*.dump.part "$(dirname "$target")"/.stage-*
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

check_keep() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]] || fail "BACKUP_KEEP must be a whole number from 1, got '$1'"
}

new_stage() {
  mkdir -p "$backup_dir"
  mktemp -d "$backup_dir/.stage-XXXXXX"
}

seal_backup() {
  local stage=$1 target=$2
  local part members
  part="$(dirname "$target")/.$(basename "$target").part"
  mapfile -t members < <(ls -A "$stage")
  if ! tar -C "$stage" -cf - "${members[@]}" | age -r "$age_recipient" -o "$part"; then
    rm -f "$part"
    fail "encryption of $target failed"
  fi
  mv "$part" "$target"
  rm -rf "$stage"
  echo "encrypted $target ($(du -h "$target" | cut -f1))"
}

save_dkim() {
  local target=$1
  local services
  if ! services=$(docker compose config --services); then
    warn "could not list compose services, DKIM keys skipped"
    return 1
  fi
  if ! grep -qx mail <<< "$services"; then
    echo "no mail service, DKIM keys skipped"
    return 0
  fi
  if ! docker compose exec -T mail tar -C /etc/opendkim/keys -cf - . > "$target"; then
    rm -f "$target"
    warn "could not read DKIM keys from mail"
    return 1
  fi
}

upload_backup() {
  local file=$1
  local bucket key_id secret endpoint region name prefix
  local prefixes=(daily)
  bucket=$(env_value BACKUP_S3_BUCKET "")
  key_id=$(env_value BACKUP_S3_ACCESS_KEY_ID "")
  secret=$(env_value BACKUP_S3_SECRET_ACCESS_KEY "")
  if [ -z "$bucket" ] || [ -z "$key_id" ] || [ -z "$secret" ]; then
    warn "BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY_ID or BACKUP_S3_SECRET_ACCESS_KEY is not set, upload skipped"
    return 0
  fi
  endpoint=$(env_value BACKUP_S3_ENDPOINT https://storage.yandexcloud.net)
  region=$(env_value BACKUP_S3_REGION ru-central1)
  name=$(basename "$file")
  if [ "$(date -u +%u)" = 7 ]; then
    prefixes+=(weekly)
  fi
  for prefix in "${prefixes[@]}"; do
    if ! printf 'user = "%s:%s"\n' "$key_id" "$secret" |
      curl -fsS -m 900 -o /dev/null -K - --aws-sigv4 "aws:amz:$region:s3" \
        -H "x-amz-content-sha256: UNSIGNED-PAYLOAD" -T "$file" "$endpoint/$bucket/$prefix/$name"; then
      fail "upload of $name to $bucket/$prefix failed"
    fi
    echo "uploaded $name to $bucket/$prefix/"
  done
}

rotate_backups() {
  local dir=$1 keep=$2 prefix=${3:-lecturo}
  local old file
  check_keep "$keep"
  mapfile -t old < <(
    {
      compgen -G "$dir/$prefix-*.dump" || true
      compgen -G "$dir/$prefix-*.tar.age" || true
    } | sort -r | tail -n +$((keep + 1))
  )
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
