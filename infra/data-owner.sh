#!/bin/sh
set -eu

backups=$1
logs=$2
storage=$3

mkdir -p "$backups" "$logs" "$storage"

chgrp 1500 "$backups"
chmod g+rwxs "$backups"

chown 0:0 "$logs"
chmod 1777 "$logs"
find "$logs" -mindepth 1 \( ! -user 1000 -o ! -group 1000 \) ! -name 'caddy*' ! -name 'mail.log*' -exec chown -h 1000:1000 {} +

find "$storage" \( ! -user 1000 -o ! -group 1000 \) -exec chown -h 1000:1000 {} +
