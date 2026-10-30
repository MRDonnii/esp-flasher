#!/bin/sh
# Local CA + server certificate for the standalone (Docker/Unraid) mode. WebSerial only works on a secure page, so the
# flasher runs HTTPS; install ca.crt on the PC once and the browser trusts it. The addresses come from the setup page
# (settings.json "hosts") plus FLASHER_HOSTS; the certificate is reissued whenever that list changes or it nears expiry.
# Not used as a Home Assistant app: there Home Assistant's own HTTPS (Ingress) is used.
set -e
C=${FLASHER_CONFIG:-/config}/certs
mkdir -p "$C"

if [ ! -f "$C/ca.key" ]; then
  echo "Laver lokal CA ..."
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -sha256 \
    -keyout "$C/ca.key" -out "$C/ca.crt" -subj "/CN=ESP Flasher lokal CA" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
fi

# Addresses: always localhost, then FLASHER_HOSTS (e.g. "IP:192.168.1.5,DNS:nas.local") and the ones from setup
SAN="DNS:localhost,IP:127.0.0.1"
[ -n "$FLASHER_HOSTS" ] && SAN="$SAN,$FLASHER_HOSTS"
if [ -f "${FLASHER_CONFIG:-/config}/settings.json" ]; then
  EXTRA=$(python3 - <<'EOF'
import ipaddress, json, os
try:
    hosts = json.load(open(os.path.join(os.environ.get("FLASHER_CONFIG", "/config"), "settings.json"))).get("hosts", [])
except Exception:
    hosts = []
out = []
for h in hosts:
    try:
        ipaddress.ip_address(h); out.append("IP:" + h)
    except ValueError:
        out.append("DNS:" + h)
print(",".join(out))
EOF
)
  [ -n "$EXTRA" ] && SAN="$SAN,$EXTRA"
fi

SAN=$(echo "$SAN" | tr ',' '\n' | awk 'NF && !seen[$0]++' | paste -sd, -)

if [ ! -f "$C/server.crt" ] || ! openssl x509 -checkend 2592000 -noout -in "$C/server.crt" >/dev/null 2>&1 \
   || [ "$(cat "$C/hosts" 2>/dev/null)" != "$SAN" ]; then
  echo "Laver servercertifikat for $SAN ..."
  openssl req -newkey rsa:2048 -nodes -keyout "$C/server.key.new" -out "$C/server.csr" -subj "/CN=ESP Flasher" 2>/dev/null
  printf 'subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' \
    "$SAN" > "$C/ext.cnf"
  openssl x509 -req -in "$C/server.csr" -CA "$C/ca.crt" -CAkey "$C/ca.key" -CAcreateserial \
    -days 825 -sha256 -extfile "$C/ext.cnf" -out "$C/server.crt.new" 2>/dev/null
  mv "$C/server.key.new" "$C/server.key"
  mv "$C/server.crt.new" "$C/server.crt"
  echo "$SAN" > "$C/hosts"
  rm -f "$C/server.csr"
fi
chmod 600 "$C/ca.key" "$C/server.key"
