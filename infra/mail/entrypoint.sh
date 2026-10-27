#!/bin/sh
set -eu

domain=${MAIL_DOMAIN:?MAIL_DOMAIN is not set}
selector=${DKIM_SELECTOR:-mail}
keys=/etc/opendkim/keys
tls=/etc/postfix/tls
networks="127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16"

mkdir -p "$keys" "$tls"
if [ ! -f "$keys/$selector.private" ]; then
  opendkim-genkey -b 2048 -d "$domain" -s "$selector" -D "$keys"
fi
chown -R opendkim:opendkim "$keys"
chmod 700 "$keys"
chmod 600 "$keys/$selector.private"

cat > /etc/opendkim/opendkim.conf <<CONF
Syslog yes
UMask 007
Mode s
Canonicalization relaxed/simple
Domain $domain
Selector $selector
KeyFile $keys/$selector.private
Socket inet:8891@127.0.0.1
InternalHosts $(echo "$networks" | tr ' ' ',')
OversignHeaders From
UserID opendkim:opendkim
AutoRestart yes
AutoRestartRate 10/1h
CONF

if [ ! -f "$tls/cert.pem" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$domain" \
    -keyout "$tls/key.pem" -out "$tls/cert.pem" 2>/dev/null
  chmod 600 "$tls/key.pem"
fi

postconf -e \
  "compatibility_level = 3.6" \
  "myhostname = $domain" \
  "mydomain = $domain" \
  "myorigin = $domain" \
  "mydestination =" \
  "local_transport = error:local delivery is disabled" \
  "alias_maps =" \
  "alias_database =" \
  "inet_interfaces = all" \
  "inet_protocols = ipv4" \
  "mynetworks = $networks" \
  "smtpd_relay_restrictions = permit_mynetworks, reject" \
  "smtpd_recipient_restrictions = permit_mynetworks, reject" \
  "local_header_rewrite_clients = permit_mynetworks" \
  "always_add_missing_headers = yes" \
  "smtpd_tls_cert_file = $tls/cert.pem" \
  "smtpd_tls_key_file = $tls/key.pem" \
  "smtpd_tls_security_level = may" \
  "smtp_tls_security_level = may" \
  "smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt" \
  "smtp_tls_loglevel = 1" \
  "smtpd_milters = inet:127.0.0.1:8891" \
  "non_smtpd_milters = inet:127.0.0.1:8891" \
  "milter_default_action = tempfail" \
  "maximal_queue_lifetime = 1d" \
  "bounce_queue_lifetime = 1d"
postconf -M "submission/inet=submission inet n - n - - smtpd"

rm -f /dev/log
syslogd -n -s 0 -O /dev/stdout &
while [ ! -S /dev/log ]; do
  sleep 0.1
done
opendkim -x /etc/opendkim/opendkim.conf
dns-records.sh

exec postfix start-fg
