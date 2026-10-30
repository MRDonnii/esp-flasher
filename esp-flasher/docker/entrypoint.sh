#!/bin/sh
# ESP Flasher start-up. As a Home Assistant app (/data/options.json exists) it serves Ingress on 8099 and takes its
# settings from the app configuration; standalone (Docker/Unraid) it serves HTTPS on 443 with a local CA and asks for
# its settings on the first visit (setup page). Firmware ships in the image (/app/firmware); a maintainer can serve
# their own builds from <config>/firmware by putting a file named .local there (tools/publish.py does).
set -e
if [ -f /data/options.json ]; then MODE=ha; CONF=/data; else MODE=docker; CONF=/config; fi
FLASHER_VERSION=$(cat /app/VERSION 2>/dev/null || echo dev)
export FLASHER_MODE=$MODE FLASHER_CONFIG=$CONF FLASHER_VERSION
mkdir -p "$CONF"
# nginx (its own user) may pass through to certs/ca.crt and firmware/, but not list the folder; secrets.json stays 600
chmod 711 "$CONF" 2>/dev/null || true
[ -f "$CONF/secrets.json" ] && chmod 600 "$CONF/secrets.json"

FW=/app/firmware
if [ "$MODE" = docker ] && [ -f "$CONF/firmware/.local" ] && [ -f "$CONF/firmware/catalog.json" ]; then
  FW="$CONF/firmware"; chmod -R a+rX "$FW"
fi
echo "ESP Flasher $FLASHER_VERSION – tilstand: $MODE, firmware fra $FW"

if [ "$MODE" = docker ]; then
  sh /app/certs.sh
  TPL=/app/nginx-docker.conf
else
  TPL=/app/nginx-ha.conf
fi
sed "s#@FW@#$FW#g; s#@CONF@#$CONF#g" "$TPL" > /tmp/nginx.conf
sed "s#@FW@#$FW#g" /app/nginx-common.inc.tpl > /app/nginx-common.inc 2>/dev/null || true

# The API keeps running even if it crashes once
( while true; do python3 /app/api.py; echo "api stoppede – genstarter"; sleep 2; done ) &
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
