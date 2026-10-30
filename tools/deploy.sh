#!/bin/bash
# Build the ESP Flasher image on your own Docker host (e.g. Unraid) and (re)start the container, with rollback.
# Reads tools/config.local.json (copy config.example.json). Not needed for the Home Assistant app.
#   tools/deploy.sh               build + swap the container, then publish your firmware builds (tools/publish.py)
#   tools/deploy.sh --no-fw       only the container
#   tools/deploy.sh --test 8444   a separate test container on port 8444 with its own empty settings (/tmp)
set -euo pipefail
cd "$(dirname "$0")/.."
cfg() { python3 -c "import json,os,sys; v=json.load(open('tools/config.local.json')).get('$1','${2:-}'); print(os.path.expanduser(str(v)))"; }
[ -f tools/config.local.json ] || { echo "Mangler tools/config.local.json (kopiér tools/config.example.json)"; exit 1; }
HOST=$(cfg host); PORT=$(cfg port 8443); APPDATA=$(cfg appdata /mnt/user/appdata/esp-flasher); HOSTS=$(cfg hosts)
NAME=ESP-Flasher
if [ "${1:-}" = "--test" ]; then
  NAME=ESP-Flasher-test; PORT=${2:-8444}; APPDATA=/tmp/esp-flasher-test
fi
WEBHOST=${HOST#*@}
KEY=$(mktemp); trap 'rm -f "$KEY"' EXIT
install -m600 "$(cfg ssh_key)" "$KEY"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST")
VERSION=$(sed -n 's/^version: *"\{0,1\}\([^"]*\)"\{0,1\}/\1/p' esp-flasher/config.yaml)

echo "Sender ESP Flasher $VERSION til $WEBHOST ..."
tar -C esp-flasher -cf - Dockerfile docker site firmware \
  | "${SSH[@]}" 'rm -rf /tmp/esp-flasher-build && mkdir -p /tmp/esp-flasher-build && tar -C /tmp/esp-flasher-build -xf -'

"${SSH[@]}" bash -s <<EOF
set -e
cd /tmp/esp-flasher-build
docker build -q --build-arg BUILD_VERSION=$VERSION -t esp-flasher:latest . >/dev/null
mkdir -p "$APPDATA"
docker rm -f $NAME-new >/dev/null 2>&1 || true
docker create --name $NAME-new --restart unless-stopped \
  -p $PORT:443 -v "$APPDATA":/config -e FLASHER_HOSTS="$HOSTS" \
  --label net.unraid.docker.managed=dockerman \
  --label net.unraid.docker.webui=https://$WEBHOST:$PORT/ \
  --label net.unraid.docker.icon=https://raw.githubusercontent.com/esphome/esphome-docs/current/images/logo.svg \
  esp-flasher:latest >/dev/null
docker stop -t 10 $NAME >/dev/null 2>&1 || true
docker rm -f $NAME-old >/dev/null 2>&1 || true
docker rename $NAME $NAME-old 2>/dev/null || true
docker rename $NAME-new $NAME
ok=
docker start $NAME >/dev/null
for i in \$(seq 1 20); do
  sleep 1
  if docker exec $NAME wget -qO- --no-check-certificate https://127.0.0.1/healthz >/dev/null 2>&1; then ok=1; break; fi
done
if [ -n "\$ok" ]; then
  docker rm -f $NAME-old >/dev/null 2>&1 || true
  docker image prune -f >/dev/null
  echo "$NAME kører på https://$WEBHOST:$PORT/"
else
  echo "Ny container startede ikke – ruller tilbage:"; docker logs $NAME 2>&1 | tail -15
  docker rm -f $NAME >/dev/null 2>&1 || true
  docker rename $NAME-old $NAME 2>/dev/null && docker start $NAME >/dev/null || true
  exit 1
fi
rm -rf /tmp/esp-flasher-build
EOF

[ "$NAME" = ESP-Flasher ] || exit 0

# Unraid template so the container shows up (and can be edited) in the Docker tab
"${SSH[@]}" "[ -d /boot/config/plugins/dockerMan ] && cat > /boot/config/plugins/dockerMan/templates-user/my-ESP-Flasher.xml || cat >/dev/null" <<EOF
<?xml version="1.0"?>
<Container version="2">
  <Name>ESP-Flasher</Name>
  <Repository>esp-flasher:latest</Repository>
  <Network>bridge</Network>
  <Shell>sh</Shell>
  <Privileged>false</Privileged>
  <Overview>Flash ESP32 firmware from the browser over USB (Chrome/Edge). Name, Wi-Fi and admin code are set on the setup page the first time it is opened, and kept in /config. Install the certificate from the page once.</Overview>
  <Category>Tools:</Category>
  <WebUI>https://[IP]:[PORT:443]/</WebUI>
  <Icon>https://raw.githubusercontent.com/esphome/esphome-docs/current/images/logo.svg</Icon>
  <Config Name="HTTPS" Target="443" Default="8443" Mode="tcp" Type="Port" Display="always" Required="true">$PORT</Config>
  <Config Name="Config" Target="/config" Default="/mnt/user/appdata/esp-flasher" Mode="rw" Type="Path" Display="always" Required="true">$APPDATA</Config>
  <Config Name="Ekstra adresser i certifikatet" Target="FLASHER_HOSTS" Default="" Description="Fx IP:192.168.1.10,DNS:nas.local - kan også skrives på opsætningssiden" Mode="" Type="Variable" Display="advanced" Required="false">$HOSTS</Config>
</Container>
EOF

[ "${1:-}" = "--no-fw" ] || python3 tools/publish.py
