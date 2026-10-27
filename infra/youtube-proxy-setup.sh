#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "usage: youtube-proxy-setup.sh <ip of the main server> [port]" >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "run as root" >&2
  exit 1
fi

main_ip="$1"
port="${2:-1080}"
if ! [[ "$main_ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  echo "main server ip must be IPv4" >&2
  exit 1
fi
proxy_user=ytproxy

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y dante-server ufw openssl

interface="$(ip -o -4 route show to default | awk '{print $5; exit}')"
public_ip="$(ip -o -4 addr show dev "$interface" | awk '{split($4, a, "/"); print a[1]; exit}')"

if ! id "$proxy_user" >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$proxy_user"
fi
password="$(openssl rand -hex 24)"
echo "$proxy_user:$password" | chpasswd

cat > /etc/danted.conf <<EOF
logoutput: syslog
internal: $interface port = $port
external: $interface
clientmethod: none
socksmethod: username
user.privileged: root
user.unprivileged: nobody

client pass {
  from: $main_ip/32 to: 0.0.0.0/0
  log: error
}

socks block {
  from: 0.0.0.0/0 to: 127.0.0.0/8
  log: error
}

socks block {
  from: 0.0.0.0/0 to: 10.0.0.0/8
  log: error
}

socks block {
  from: 0.0.0.0/0 to: 172.16.0.0/12
  log: error
}

socks block {
  from: 0.0.0.0/0 to: 192.168.0.0/16
  log: error
}

socks block {
  from: 0.0.0.0/0 to: 169.254.0.0/16
  log: error
}

socks pass {
  from: $main_ip/32 to: 0.0.0.0/0
  command: connect
  log: error
}
EOF

systemctl enable danted
systemctl restart danted

ssh_ports="$(sshd -T | awk '/^port /{print $2}')"
if [ -z "$ssh_ports" ]; then
  echo "could not find sshd port, firewall left unchanged" >&2
  exit 1
fi
for ssh_port in $ssh_ports; do
  ufw allow "$ssh_port/tcp"
done
ufw allow from "$main_ip" to any port "$port" proto tcp
ufw --force enable

echo "YOUTUBE_PROXY=socks5h://$proxy_user:$password@$public_ip:$port"
