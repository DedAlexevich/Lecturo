#!/bin/sh
set -eu

root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
log="$tmp/service.log"
: > "$log"
: > "$log.1"
chmod 644 "$log" "$log.1"
cat > "$tmp/write-log.sh" <<'EOF'
awk 'BEGIN { for (i = 0; i < 110000; i++) print "0123456789" }'
sleep 1
EOF

LOG_MAX_MB=1 LOG_BACKUP_COUNT=3 LOG_FILE_MODE=640 sh "$root/infra/log-to-file.sh" "$log" sh "$tmp/write-log.sh" >/dev/null

attempt=0
while [ "$attempt" -lt 50 ] && [ ! -s "$log.1" ]; do
  sleep 0.1
  attempt=$((attempt + 1))
done

test -s "$log.1"
test -f "$log.2"
test "$(stat -c '%a' "$log")" = 640
test "$(stat -c '%a' "$log.1")" = 640
test "$(stat -c '%a' "$log.2")" = 640
