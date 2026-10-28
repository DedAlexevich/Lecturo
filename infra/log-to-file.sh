#!/bin/sh
set -eu

file=$1
shift
max=$(( ${LOG_MAX_MB:-10} * 1048576 ))
keep=${LOG_BACKUP_COUNT:-5}
resync_lines=100

mkdir -p "$(dirname "$file")"
: >> "$file"
fifo=$(mktemp -u)
mkfifo "$fifo"

rotate() {
  if [ "$keep" -lt 1 ]; then
    : > "$file"
    return
  fi
  i=$((keep - 1))
  while [ "$i" -ge 1 ]; do
    if [ -f "$file.$i" ]; then
      mv "$file.$i" "$file.$((i + 1))"
    fi
    i=$((i - 1))
  done
  mv "$file" "$file.1"
}

(
  exec 3>>"$file"
  size=$(wc -c < "$file")
  lines=0
  while IFS= read -r line; do
    printf '%s\n' "$line"
    printf '%s\n' "$line" >&3
    lines=$((lines + 1))
    if [ "$lines" -ge "$resync_lines" ]; then
      size=$(wc -c < "$file")
      lines=0
    else
      size=$((size + ${#line} + 1))
    fi
    if [ "$size" -ge "$max" ]; then
      exec 3>&-
      rotate
      exec 3>>"$file"
      size=0
      lines=0
    fi
  done < "$fifo"
) &

exec "$@" > "$fifo" 2>&1
