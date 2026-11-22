# Tredjepartskode og firmware

**ESP Flasher selv** er udgivet under PolyForm Noncommercial License 1.0.0 (se [LICENSE](LICENSE)). Det gælder webappen, Home Assistant-add-on'en, Docker-opsætningen og værktøjerne.

Det gælder **ikke** filerne nedenfor. De er andres værker og har deres egne licenser.

| Hvad | Hvor | Licens | Kilde |
|---|---|---|---|
| ESP Web Tools (flash fra browseren) | `esp-flasher/site/vendor/esp-web-tools/` | Apache-2.0 (se `LICENSE` i mappen) | https://github.com/esphome/esp-web-tools |
| WLED 16.0.1 (IKEA SKAFTSÄRV) | `esp-flasher/firmware/wled-skaftsarv-c3/` | EUPL-1.2 (se `LICENSE-EUPL-1.2.txt` og `NOTICE.txt`) | https://github.com/wled/WLED/releases/tag/v16.0.1 |
| Qlima Control (ESPHome-firmware) | `esp-flasher/firmware/qlima-control-c3/` | GPL-3.0 (ESPHome) | https://github.com/MRDonnii/qlima-control |
| Tesla BLE-proxy (ESPHome-firmware) | `esp-flasher/firmware/tesla-ble-proxy-c3/` | GPL-3.0 (ESPHome) | ESPHome: https://github.com/esphome/esphome |
| Zigbee Presence (ESP-IDF-firmware) | `esp-flasher/firmware/shs-h2-*/` | Egen kode. Indeholder ESP-IDF (Apache-2.0) og Espressifs Zigbee-biblioteker (Espressifs licens) | https://github.com/espressif/esp-idf |

Firmwarefilerne bliver kun leveret videre. ESP Flasher ændrer dem ikke.
