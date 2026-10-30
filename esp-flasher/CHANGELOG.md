# Ændringer

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
