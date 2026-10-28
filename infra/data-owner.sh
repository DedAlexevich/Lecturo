#!/bin/sh
set -eu

for dir in "$@"; do
  mkdir -p "$dir"
  find "$dir" \( ! -user 1000 -o ! -group 1000 \) ! -name 'caddy.log*' ! -name 'mail.log*' -exec chown -h 1000:1000 {} +
done
