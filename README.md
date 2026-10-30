# ESP Flasher

Flash ESP32-firmware direkte fra browseren (Chrome/Edge) med et USB-kabel. Firmwaren følger med i appen:

| Firmware | Chip | Type |
|---|---|---|
| Zigbee Presence (LD2410 / LD2410 + LD2450) | ESP32-H2 | Zigbee-router til Zigbee2MQTT |
| Qlima Control | ESP32-C3 | ESPHome / Wi-Fi |
| Tesla BLE-proxy | ESP32-C3 | ESPHome Bluetooth-proxy |

Der er ingen personlige indstillinger i repoet eller i firmwaren. Navn, Wi-Fi og admin-kode skrives ind første gang, du bruger appen.

## Som Home Assistant-app (anbefalet)

Den nemmeste vej er at køre den som app. Den åbnes i Home Assistants sidepanel og bruger Home Assistants egen https, så du ikke skal lave et certifikat.

1. **Indstillinger → Apps → App store → ⋮ → Repositories**, og tilføj `https://github.com/MRDonnii/esp-flasher`.
2. Installér **ESP Flasher**.
3. Udfyld **Konfiguration**: navn og evt. Wi-Fi.
4. Start appen, og slå **Vis i sidepanel** til.

USB fra browseren kræver, at siden er åbnet over **https**, fx Nabu Casa eller din egen https-adresse til Home Assistant.

Er du på `http://<ip>:8123`, viser siden selv vejen videre:
- en knap til din https-adresse, eller
- Chrome-flaget `chrome://flags/#unsafely-treat-insecure-origin-as-secure` for netop den adresse.

## Som Docker-container (fx Unraid)

```sh
docker build -t esp-flasher esp-flasher/
docker run -d --name ESP-Flasher --restart unless-stopped \
  -p 8443:443 -v /mnt/user/appdata/esp-flasher:/config esp-flasher
```

Åbn `https://<server-ip>:8443/`. Første gang kommer en opsætningsside med:
- **Navn** på siden
- **Admin-kode**, der beskytter indstillingerne og den gemte Wi-Fi-kode
- **Wi-Fi** til nye enheder (valgfrit)
- **Adresser**, siden åbnes på, fx serverens IP og `nas.local`. De kommer med i certifikatet.

Containeren laver selv en lokal CA og et certifikat i `/config/certs`. Installér `ca.crt` (link på siden) én gang på pc'en, så stoler Chrome på siden. Opsætningssiden viser hvordan på Windows, macOS og Linux.

Indstillingerne ligger i `/config`:
- `settings.json`: navn, adresser og Home Assistant-adresse
- `secrets.json`: admin-kode (hashet), Wi-Fi og sessionsnøgle. Kun læsbar for root.

Glemt admin-koden? Slet `/config/secrets.json`, så kommer opsætningen igen.

## Flash

1. Sæt ESP'en i med et USB-**datakabel**.
2. Vælg chip og firmware, og tryk **Flash via USB**.
3. Vælg **Erase device**, hvis det er en ny enhed. Uden erase bevares indstillinger, Wi-Fi og Zigbee-parring.
4. Wi-Fi-enheder: tryk **Send Wi-Fi** bagefter, så kommer de på dit net.
5. Zigbee-enheder: åbn *Permit join* i Zigbee2MQTT.

Finder browseren ikke ESP'en, så hold **BOOT** nede, tryk **RESET** og slip BOOT.

## For vedligeholderen

Firmwaren beskrives i `firmwares.json`, og `tools/publish.py` samler den i `esp-flasher/firmware/`. Mappen committes, så appen og containeren har den med.

| Kildetype | Hvad publish.py gør |
|---|---|
| `idf` | Kopierer delene fra ESP-IDF-buildets `flash_args`. |
| `manifest_url` | Henter en udgivet ESP Web Tools-manifest. |
| `esphome` | Bygger en **generisk** kopi: API-nøglen fjernes (Home Assistant sætter den, når enheden tilføjes), og OTA-koden fjernes. Bruger kilden `!secret`, stopper den. Firmwaren tjekkes også for værdier fra din `secrets.yaml`. |

```sh
cp tools/config.example.json tools/config.local.json   # din server, nøgle og ESPHome (ikke i git)
tools/publish.py             # byg esp-flasher/firmware
tools/publish.py --upload    # ... og læg den på din egen Docker-vært (.local vinder over imagets)
tools/deploy.sh              # byg imaget på din Docker-vært og skift containeren (med rollback)
tools/deploy.sh --test 8444  # en separat testcontainer med tomme indstillinger
```

Ny firmware til Home Assistant-appen:
1. Kør `tools/publish.py`.
2. Bump `version` i `esp-flasher/config.yaml`, og skriv i `esp-flasher/CHANGELOG.md`.
3. Commit og push. Home Assistant viser så en opdatering til appen.
