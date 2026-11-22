# ESP Flasher

Flash ESP32-firmware direkte fra browseren med et USB-kabel. Siden åbnes i Home Assistants sidepanel.

Der følger **ingen firmware** med. Du laver selv dine profiler og lægger dem i et profil-katalog, fx dit eget GitHub-repo (gerne privat). Formatet står i [README'en](https://github.com/MRDonnii/esp-flasher#profil-kataloger).

## Kom i gang

1. Udfyld **Konfiguration**:
   - **Navn**: vises øverst på siden.
   - **Wi-Fi** (valgfrit): netværket nye Wi-Fi-enheder skal på.
   - **Profil-kataloger**: ét punkt pr. katalog.
     - `url`: mappen med `catalog.json`, fx `https://github.com/EJER/REPO/tree/main/profiles`.
     - `token` (kun privat GitHub-repo): et *fine-grained* token med adgang til netop det ene repo og kun **Contents: Read-only**.
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

## Profiler

Appen tjekker dine kataloger hver halve time og henter nye profiler selv, så du ikke skal opdatere appen for at få dem. Du kan også trykke **Søg efter ny** nederst på siden.

- Alt hentes af appen selv, ikke af browseren. Tokenet bliver i appens indstillinger (og i Home Assistants backup) og sendes aldrig til browseren.
- Hver fil tjekkes mod kataloget (sha256), før den bruges.
- Kan et katalog ikke hentes, bruges de profiler, der allerede er hentet.
- Ændrer du kataloger, så genstart appen.

## Opdatering af enheder

- **Zigbee-enheder** opdateres typisk trådløst i Zigbee2MQTT (OTA-fanen).
- **ESPHome-enheder** opdateres fra ESPHome i Home Assistant.

USB er kun til den første flash, eller hvis en enhed skal reddes.
