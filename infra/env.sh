#!/usr/bin/env bash
env_value() {
  local value="${!1:-}"
  if [ -z "$value" ] && [ -f .env ]; then
    value=$(sed -n "s/^$1=//p" .env | tail -n 1 | tr -d "\"'\r")
  fi
  echo "${value:-${2:-}}"
}
