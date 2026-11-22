# ESP Flasher

Flash ESP32-firmware direkte fra browseren (Chrome/Edge) med et USB-kabel.

ESP Flasher er kun selve flasheren. **Der følger ingen firmware med.** Du laver selv dine profiler (firmware + beskrivelse) og lægger dem i et [profil-katalog](#profil-kataloger), fx i dit eget GitHub-repo. Det må gerne være privat. Så henter flasheren dem selv.

Der er ingen personlige indstillinger i repoet. Navn, Wi-Fi, admin-kode og dine kataloger skrives ind, når du har installeret den.

## Som Home Assistant-app (anbefalet)

Den nemmeste vej er at køre den som app. Den åbnes i Home Assistants sidepanel og bruger Home Assistants egen https, så du ikke skal lave et certifikat.

1. **Indstillinger → Apps → App store → ⋮ → Repositories**, og tilføj `https://github.com/MRDonnii/esp-flasher`.
2. Installér **ESP Flasher**.
3. Udfyld **Konfiguration**: navn, evt. Wi-Fi og dine **Profil-kataloger** (adresse og evt. token, se [Profil-kataloger](#profil-kataloger)).
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

Bagefter tilføjer du dine profil-kataloger under **⚙️ Indstillinger → Profil-kataloger**. Ét katalog kan også gives som miljøvariabler: `FLASHER_CATALOG_URL` og evt. `FLASHER_CATALOG_TOKEN`.

Containeren laver selv en lokal CA og et certifikat i `/config/certs`. Installér `ca.crt` (link på siden) én gang på pc'en, så stoler Chrome på siden. Opsætningssiden viser hvordan på Windows, macOS og Linux.

Indstillingerne ligger i `/config`:
- `settings.json`: navn, adresser og Home Assistant-adresse
- `secrets.json`: admin-kode (hashet), Wi-Fi, sessionsnøgle og dine kataloger med tokens. Kun læsbar for root.

Glemt admin-koden? Slet `/config/secrets.json`, så kommer opsætningen igen.

## Flash

1. Sæt ESP'en i med et USB-**datakabel**.
2. Vælg chip og firmware, og tryk **Flash via USB**.
3. Vælg **Erase device**, hvis det er en ny enhed. Uden erase bevares indstillinger, Wi-Fi og Zigbee-parring.
4. Wi-Fi-enheder: tryk **Send Wi-Fi** bagefter, så kommer de på dit net.
5. Zigbee-enheder: åbn *Permit join* i Zigbee2MQTT.

Finder browseren ikke ESP'en, så hold **BOOT** nede, tryk **RESET** og slip BOOT.

## Profil-kataloger

Et profil-katalog er en mappe med en `catalog.json` og én undermappe pr. profil:

```
profiles/
├── catalog.json
└── min-sensor-c3/
    ├── manifest.json
    └── firmware.factory.bin
```

**Adressen** er mappen med `catalog.json`. Alle disse virker:
- `https://github.com/EJER/REPO/tree/main/profiles`
- `https://raw.githubusercontent.com/EJER/REPO/main/profiles/`
- en hvilken som helst https-mappe, fx `https://eksempel.dk/esp/profiles/catalog.json`

**Privat GitHub-repo:** lav et *fine-grained personal access token* på GitHub (**Settings → Developer settings → Fine-grained tokens**):
- *Repository access*: **Only select repositories** → kun dit profil-repo
- *Permissions*: **Contents: Read-only** (intet andet)

Skriv tokenet ved kataloget. Det gemmes kun i appens indstillinger (Home Assistant) eller i `secrets.json` (Docker) og sendes aldrig til browseren. Alt hentes på serveren: privat repo via GitHubs API med tokenet, ellers direkte. Derfor kræver kataloget heller ikke CORS.

`catalog.json`:

```json
{
  "generated": "2026-11-22T12:00:00",
  "firmwares": [
    {
      "id": "min-sensor-c3",
      "name": "Min sensor",
      "chip": "ESP32-C3",
      "kind": "wifi",
      "kindLabel": "Wi-Fi · ESPHome",
      "status": "testet",
      "summary": "Kort beskrivelse, der står på kortet.",
      "features": ["Wi-Fi sættes i flash-dialogen (Improv)"],
      "wiring": [["Sensor SDA", "GPIO6"], ["Sensor SCL", "GPIO7"]],
      "after": "Hvad man gør efter flash.",
      "version": "1.0.0",
      "date": "2026-11-22",
      "manifest": "min-sensor-c3/manifest.json",
      "sha256": "0123456789ab"
    }
  ]
}
```

- **Påkrævet:** `id` (bogstaver, tal, `.`, `_`, `-`), `name`, `chip`, `manifest` (altid `<id>/manifest.json`) og `sha256`.
- **`sha256`:** de første 12 hex-tegn af SHA-256 over manifestets dele lagt efter hinanden i manifestets rækkefølge. En profil bruges kun, hvis den passer.
- **Valgfrit:** `kind` (`wifi`/`zigbee`), `kindLabel`, `status`, `summary`, `features`, `wiring`, `after`, `after_wifi`, `ota`, `version`, `date`, `changelog`.

`<id>/manifest.json` er et almindeligt [ESP Web Tools-manifest](https://github.com/esphome/esp-web-tools). Delenes `path` er rene filnavne i samme mappe:

```json
{
  "name": "Min sensor",
  "version": "1.0.0",
  "new_install_prompt_erase": true,
  "builds": [{"chipFamily": "ESP32-C3", "parts": [{"path": "firmware.factory.bin", "offset": 0}]}]
}
```

`sha256` kan regnes sådan:

```sh
python3 -c 'import hashlib,json,sys; d=sys.argv[1]; m=json.load(open(d+"/manifest.json")); h=hashlib.sha256(); [h.update(open(d+"/"+p["path"],"rb").read()) for p in m["builds"][0]["parts"]]; print(h.hexdigest()[:12])' profiles/min-sensor-c3
```

Har du flere kataloger, vises de samlet. Findes et `id` i flere, vinder det første katalog på listen.

**Opdateringer:** flasheren tjekker katalogerne hver halve time og henter kun det, der er ændret. Du kan også trykke **Søg efter ny** nederst på siden.
- Hver fil tjekkes mod kataloget (sha256), før den bruges.
- Skiftet sker på én gang, så siden aldrig viser en halv opdatering.
- Kan kataloget ikke hentes, bruges de profiler, der allerede er hentet.
- Fjerner du et katalog, forsvinder dets profiler fra siden.

**Delt firmware må ikke indeholde personlige værdier.** Byg fx ESPHome-firmware uden fast API-nøgle (`api: encryption: {}`), så Home Assistant giver hver enhed sin egen nøgle, når den tilføjes.

## For vedligeholderen

```sh
cp tools/config.example.json tools/config.local.json   # din Docker-vært (ikke i git)
tools/deploy.sh              # byg imaget på din Docker-vært og skift containeren (med rollback)
tools/deploy.sh --test 8444  # en separat testcontainer med tomme indstillinger
```

En vedligeholder kan servere sine egne builds direkte: læg et katalog i `<config>/firmware/` på Docker-værten sammen med en tom fil `.local`. Så bruges den mappe i stedet for katalogerne.

**Ændringer i selve siden eller appen:** bump `version` i `esp-flasher/config.yaml`, og skriv i `esp-flasher/CHANGELOG.md`. Så tilbyder Home Assistant en opdatering.

## Licens

ESP Flasher er udgivet under [PolyForm Noncommercial License 1.0.0](LICENSE): fri brug til ikke-kommercielle formål (privat, hjem, hobby, undervisning og foreninger). Kommerciel brug kræver skriftlig tilladelse fra ophavsmanden.

ESP Web Tools, som flasheren bruger, er Apache-2.0. Se [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Der følger ingen firmware med. Den firmware, du flasher fra dine egne kataloger, har sin egen licens, og det er dit ansvar at overholde den, hvis du deler den.
