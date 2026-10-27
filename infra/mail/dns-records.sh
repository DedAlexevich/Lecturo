#!/bin/sh
set -eu

domain=${MAIL_DOMAIN:?MAIL_DOMAIN is not set}
selector=${DKIM_SELECTOR:-mail}
public_key=$(openssl pkey -in "/etc/opendkim/keys/$selector.private" -pubout -outform DER | base64 -w 0)

echo "DNS records for $domain:"
echo "$domain TXT \"v=spf1 a ~all\""
echo "$selector._domainkey.$domain TXT \"v=DKIM1; k=rsa; p=$public_key\""
echo "_dmarc.$domain TXT \"v=DMARC1; p=none; adkim=r; aspf=r\""
echo "PTR of the server IP: $domain"
