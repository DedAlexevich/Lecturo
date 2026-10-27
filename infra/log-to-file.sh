#!/bin/sh
set -eu

file=$1
shift
max=$(( ${LOG_MAX_MB:-10} * 1048576 ))
keep=${LOG_BACKUP_COUNT:-5}

mkdir -p "$(dirname "$file")"
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
  size=0
  if [ -f "$file" ]; then
    size=$(wc -c < "$file")
  fi
  while IFS= read -r line; do
    printf '%s\n' "$line"
    printf '%s\n' "$line" >> "$file"
    size=$((size + ${#line} + 1))
    if [ "$size" -ge "$max" ]; then
      rotate
      size=0
    fi
  done < "$fifo"
) &

exec "$@" > "$fifo" 2>&1
