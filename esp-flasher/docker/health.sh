#!/bin/sh
# Docker HEALTHCHECK for both modes
if [ -f /data/options.json ]; then
  wget -qO- http://127.0.0.1:8099/healthz >/dev/null
else
  wget -qO- --no-check-certificate https://127.0.0.1/healthz >/dev/null
fi
