#!/bin/sh
set -u

dir=/backups
keep=${BACKUP_KEEP:-7}
interval=$(( ${BACKUP_INTERVAL_HOURS:-24} * 3600 ))

case "$keep" in
  "" | *[!0-9]* | 0)
    echo "BACKUP_KEEP must be a whole number from 1, got '$keep'" >&2
    exit 1
    ;;
esac

umask 022
mkdir -p "$dir"
chmod 777 "$dir"

latest_backup() {
  ls -1 "$dir"/lecturo-*.dump 2>/dev/null | sort | tail -n 1
}

backup() {
  name="lecturo-$(date -u +%Y%m%d-%H%M%S).dump"
  part="$dir/.$name.sidecar"
  if pg_dump -Fc > "$part" && pg_restore --list "$part" > /dev/null; then
    mv "$part" "$dir/$name"
    echo "saved $dir/$name"
    ls -1 "$dir"/lecturo-*.dump | sort -r | tail -n +$((keep + 1)) | xargs -r rm -f
  else
    rm -f "$part"
    echo "backup failed" >&2
  fi
}

rm -f "$dir"/.lecturo-*.sidecar

while true; do
  last=$(latest_backup)
  wait=0
  if [ -n "$last" ]; then
    wait=$(( interval - ($(date +%s) - $(stat -c %Y "$last")) ))
  fi
  if [ "$wait" -gt 0 ]; then
    echo "next backup in ${wait}s"
    sleep "$wait"
  fi
  backup
  sleep 600
done
