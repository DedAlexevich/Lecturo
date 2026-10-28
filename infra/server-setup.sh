#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: server-setup.sh <domain> '<ssh public key of the admin>'" >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "run as root" >&2
  exit 1
fi

if [ "$(passwd -S root | awk '{print $2}')" != P ]; then
  echo "root has no password, set it with passwd first: after setup root is reachable only via su" >&2
  exit 1
fi

domain="$1"
admin_key="$2"
app_dir=/opt/lecturo
repo_url=https://github.com/DedAlexevich/Lecturo.git

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade
apt-get install -y ca-certificates curl git ufw fail2ban unattended-upgrades

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

id admin >/dev/null 2>&1 || useradd -m -s /bin/bash -N admin
install -d -m 700 -o admin -g "$(id -gn admin)" /home/admin/.ssh
touch /home/admin/.ssh/authorized_keys
grep -qxF "$admin_key" /home/admin/.ssh/authorized_keys || echo "$admin_key" >> /home/admin/.ssh/authorized_keys
chown admin: /home/admin/.ssh/authorized_keys
chmod 600 /home/admin/.ssh/authorized_keys

id deploy >/dev/null 2>&1 || useradd -m -s /bin/bash deploy
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
actions_key=$(mktemp -d)/actions
ssh-keygen -q -t ed25519 -N "" -C github-actions-deploy -f "$actions_key"
touch /home/deploy/.ssh/authorized_keys
sed -i '/github-actions-deploy$/d' /home/deploy/.ssh/authorized_keys
echo "command=\"$app_dir/infra/deploy.sh \$SSH_ORIGINAL_COMMAND\",restrict $(cat "$actions_key.pub")" >> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

if [ ! -d "$app_dir/.git" ]; then
  git clone "$repo_url" "$app_dir"
  chown -R deploy:deploy "$app_dir"
fi

if [ ! -f "$app_dir/.env" ]; then
  sed \
    -e "s|^SITE_ADDRESS=.*|SITE_ADDRESS=$domain|" \
    -e "s|^PUBLIC_URL=.*|PUBLIC_URL=https://$domain|" \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" \
    "$app_dir/.env.example" > "$app_dir/.env"
  echo "COMPOSE_FILE=docker-compose.yml:infra/compose.prod.yml" >> "$app_dir/.env"
  chown deploy:deploy "$app_dir/.env"
  chmod 600 "$app_dir/.env"
fi

install -m 644 "$app_dir/infra/backup/lecturo-backup.service" "$app_dir/infra/backup/lecturo-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now lecturo-backup.timer

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

cat > /etc/ssh/sshd_config.d/00-lecturo.conf <<SSHD
PermitRootLogin no
AllowUsers admin deploy
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
SSHD
sshd -t
systemctl try-reload-or-restart ssh

systemctl enable --now fail2ban

bash "$app_dir/infra/install-monitoring.sh"

host_ip=$(curl -fsS4 https://api.ipify.org || hostname -I | awk '{print $1}')

echo
echo "SSH_HOST=$host_ip"
echo "SSH_USER=deploy"
echo "SSH_KNOWN_HOSTS=$host_ip $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
echo "DEPLOY_URL=https://$domain"
echo "SSH_KEY:"
cat "$actions_key"
rm -rf "$(dirname "$actions_key")"
