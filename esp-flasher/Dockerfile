# ESP Flasher: web flasher (ESP Web Tools) for your own ESP firmwares, flashed over USB from Chrome/Edge on your PC.
# Runs standalone (Docker/Unraid: HTTPS + setup page) or as a Home Assistant app (Ingress). Nothing personal and no
# firmware is built in: name, Wi-Fi, addresses and the profile catalogs to flash from are set up after installing and
# kept on the data volume.
ARG BUILD_FROM=nginx:1.27-alpine
FROM nginx:1.27-alpine

RUN apk add --no-cache openssl python3

COPY docker/ /app/
COPY site/ /usr/share/nginx/html/
ARG BUILD_VERSION=dev
RUN echo "$BUILD_VERSION" > /app/VERSION \
 && chmod +x /app/entrypoint.sh /app/health.sh \
 && chmod -R a+rX /usr/share/nginx/html

ENV FLASHER_HOSTS=""
VOLUME /config
EXPOSE 443 8099
HEALTHCHECK --interval=60s --timeout=5s CMD /app/health.sh || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
