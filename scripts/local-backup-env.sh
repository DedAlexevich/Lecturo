cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -z "${BACKUP_DIR:-}" ] && ! grep -qs "^BACKUP_DIR=." .env; then
  data_dir="${DATA_DIR:-}"
  if [ -z "$data_dir" ]; then
    data_dir=$(sed -n 's/^DATA_DIR=//p' .env 2>/dev/null | tail -n 1 | tr -d "\"'\r")
  fi
  export BACKUP_DIR="${data_dir:-./data}/backups"
fi
