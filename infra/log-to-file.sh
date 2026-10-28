#!/bin/sh
set -eu

file=$1
shift
max=$(( ${LOG_MAX_MB:-10} * 1048576 ))
keep=${LOG_BACKUP_COUNT:-5}
resync_lines=100
file_mode=${LOG_FILE_MODE:-}

mkdir -p "$(dirname "$file")"
if [ -n "$file_mode" ]; then
  umask 027
fi
: >> "$file"
if [ -n "$file_mode" ]; then
  chmod "$file_mode" "$file"
  for rotated_file in "$file".*; do
    if [ -f "$rotated_file" ] && [ ! -L "$rotated_file" ]; then
      chmod "$file_mode" "$rotated_file"
    fi
  done
fi
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
