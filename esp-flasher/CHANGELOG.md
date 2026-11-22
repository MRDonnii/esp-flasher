# Ændringer

## 3.0.0

- **Ingen firmware følger med længere.** Du lægger dine egne profiler i et profil-katalog og sætter det op i appen.
  - Konfiguration: **Profil-kataloger** med adresse og evt. token til et privat GitHub-repo (fine-grained, kun læseadgang).
  - Docker: under ⚙️ Indstillinger, eller med `FLASHER_CATALOG_URL` og `FLASHER_CATALOG_TOKEN`.
  - Alt hentes på serveren. Tokenet sendes aldrig til browseren.
  - Flere kataloger vises samlet.
- Siden forklarer, hvad du skal gøre, når der ikke er nogen profiler endnu.
- Profiler, der stammer fra tidligere versioner af appen, fjernes, når appen opdateres.
- "Hent ny firmware automatisk" er fjernet. Kataloger tjekkes altid hver halve time.
- Formatet for katalog og manifest er beskrevet i README'en.

## 2.1.0

- Ny firmware kommer frem af sig selv. Appen tjekker GitHub hver halve time og henter kun det, der er ændret.
  - Hver fil kontrolleres med kataloget, før den bruges.
  - Skiftet sker på én gang, så siden aldrig viser en halv opdatering.
  - Uden internet bruges den firmware, appen allerede har.
- I bunden af siden står, hvornår firmwaren er fra. Der er også en knap, "Søg efter ny".
- En side, der står åben, viser ny firmware, så snart den er hentet. Den skifter ikke midt i en flash.
- Kan slås fra i Konfiguration ("Hent ny firmware automatisk").

## 2.0.0

- Kan installeres som Home Assistant-app. Den åbnes i sidepanelet og bruger Home Assistants https, så der ikke skal noget certifikat til.
- Kan stadig køre som en almindelig Docker-container, fx på Unraid.
  - Første gang den åbnes, kommer en opsætningsside: navn, admin-kode, Wi-Fi og adresser.
  - Opsætningen gemmes i `/config`, og koder ligger i en separat secrets-fil.
  - Containeren laver selv en lokal CA og et certifikat. Certifikatet kan hentes fra siden.
- **Send Wi-Fi**: sender det gemte Wi-Fi til enheden over USB efter flash (Improv).
- Nyt design med filtre for chip og type, ledningsdiagram og ændringslog pr. firmware.
- Siden fortæller tydeligt, hvis den er åbnet over http og derfor ikke kan få USB-adgang, og hvad man så skal gøre.
- ESPHome-firmware bygges generisk:
  - ingen API-nøgle (Home Assistant sætter den, når enheden tilføjes) og ingen OTA-kode
  - stopper, hvis der er værdier fra `secrets.yaml` i firmwaren
