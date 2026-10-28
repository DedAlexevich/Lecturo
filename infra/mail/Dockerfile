FROM alpine:3.24

RUN apk add --no-cache postfix opendkim opendkim-utils ca-certificates openssl

COPY entrypoint.sh dns-records.sh /usr/local/bin/

ENTRYPOINT ["entrypoint.sh"]
