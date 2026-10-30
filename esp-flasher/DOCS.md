# ESP Flasher

Flash ESP32-firmware direkte fra browseren med et USB-kabel. Siden åbnes i Home Assistants sidepanel.

## Kom i gang

1. Udfyld **Konfiguration**:
   - **Navn**: vises øverst på siden.
   - **Wi-Fi** (valgfrit): netværket nye Wi-Fi-enheder skal på.
2. Start appen og slå **Vis i sidepanel** til.
3. Åbn **ESP Flasher** i sidepanelet.

## Krav

- **Browser:** Chrome eller Edge på Windows, macOS eller Linux. Safari, Firefox og mobil kan ikke tale USB.
- **Adresse:** Siden skal åbnes over **https**, fx via Nabu Casa eller din egen https-adresse til Home Assistant. Det er et krav fra browseren for USB-adgang.
  - Bruger du Home Assistant på `http://<ip>:8123`, viser siden en knap til din https-adresse, hvis du har en.
  - Ellers viser den, hvordan du slår Chrome-flaget `unsafely-treat-insecure-origin-as-secure` til for netop den adresse.
- **Certifikat:** Appen behøver ikke sit eget certifikat. Den bruger Home Assistants.

## Wi-Fi efter flash

Wi-Fi-enheder kan få dit Wi-Fi sendt over USB lige efter flash med **Send Wi-Fi** (Improv).

Koden gemmes kun i appens indstillinger i Home Assistant og kommer med i Home Assistants backup.

## Opdatering af enheder

- **Zigbee-presence** opdateres trådløst i Zigbee2MQTT (OTA-fanen).
- **ESPHome-enheder** opdateres fra ESPHome i Home Assistant.

USB er kun til den første flash, eller hvis en enhed skal reddes.
