#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root" >&2
  exit 1
fi

app_dir=$(cd "$(dirname "$0")/.." && pwd)

cat > /etc/systemd/system/lecturo-health.service <<UNIT
[Unit]
Description=Lecturo health check with Telegram alert
After=docker.service

[Service]
Type=oneshot
User=deploy
StateDirectory=lecturo-health
ExecStart=$app_dir/infra/health-alert.sh
UNIT

cat > /etc/systemd/system/lecturo-health.timer <<UNIT
[Unit]
Description=Run Lecturo health check every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now lecturo-health.timer
