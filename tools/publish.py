#!/usr/bin/env python3
"""Collect the firmwares in firmwares.json into the app's firmware folder (esp-flasher/firmware, shipped in the image).

  tools/publish.py            build esp-flasher/firmware (commit it, bump the app version; the image and the app use it)
  tools/publish.py --upload   also upload it to your own Docker host's <appdata>/firmware (needs tools/config.local.json -
                              see config.example.json; marks it ".local" so it wins over the firmware in the image)

idf sources use the build folder's flash_args (bootloader, partition table, otadata and app as separate parts, so a flash
without "Erase device" leaves NVS and the Zigbee pairing alone). manifest_url sources are downloaded as they are released.
esphome sources are compiled here as a GENERIC image: the API key is left out (Home Assistant sets one when the device is
added), OTA has no key, and a source that uses !secret is refused - nothing personal ends up in a shared binary. The
result is also scanned for the values in your ESPHome secrets.yaml (when found) before it is published.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "esp-flasher", "firmware")
CFG_PATH = os.path.join(ROOT, "tools", "config.local.json")
CFG = json.load(open(CFG_PATH)) if os.path.exists(CFG_PATH) else {}
ESPHOME = os.path.expanduser(CFG.get("esphome", "esphome"))
SECRETS_YAML = os.path.expanduser(CFG.get("secrets_yaml", ""))

CHIP_FAMILY = {"esp32h2": "ESP32-H2", "esp32c6": "ESP32-C6", "esp32c3": "ESP32-C3", "esp32": "ESP32", "esp32s3": "ESP32-S3"}


def idf_parts(fw, dest):
    src = fw["source"]
    proj = os.path.normpath(os.path.join(ROOT, src["project"]))
    build = os.path.join(proj, src["build"])
    header = open(os.path.join(proj, src["header"]), encoding="utf-8").read()
    m = re.search(r'SHS_BASIC_SW_BUILD_ID\s+(?:"\\x[0-9a-fA-F]{2}"\s*)?"v?([^"]+)"', header)
    version = m.group(1) if m else "0"
    desc = json.load(open(os.path.join(build, "project_description.json")))
    chip = CHIP_FAMILY.get(desc.get("target"), desc.get("target"))
    if chip != fw["chip"]:
        sys.exit(f"{fw['id']}: build is for {chip}, catalog says {fw['chip']}")
    built = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(build, desc["app_bin"]))).strftime("%Y-%m-%d")
    parts = []
    for line in open(os.path.join(build, "flash_args")):
        line = line.split()
        if len(line) != 2 or not line[0].startswith("0x"):
            continue
        offset, rel = int(line[0], 16), line[1]
        name = os.path.basename(rel)
        if rel == desc["app_bin"]:
            name = "app.bin"
        shutil.copy2(os.path.join(build, rel), os.path.join(dest, name))
        parts.append({"path": name, "offset": offset})
    parts.sort(key=lambda p: p["offset"])
    return chip, version, built, parts, {}


def generic_yaml(text):
    """Strip the personal parts from an ESPHome config: API key (HA provisions one), OTA key/password."""
    if re.search(r"!secret\b", text):
        raise SystemExit("ESPHome-kilden bruger !secret - en delt firmware må ikke have personlige værdier indbygget")
    out, block, in_enc = [], None, False
    for line in text.splitlines():
        top = re.match(r"^([a-z_0-9]+):", line)
        if top:
            block, in_enc = top.group(1), False
        if block == "api" and re.match(r"^  encryption:", line):
            out.append("  encryption: {}  # Home Assistant sets the key when the device is added")
            in_enc = True
            continue
        if block == "api" and in_enc and re.match(r"^    ", line):
            continue
        in_enc = in_enc and not re.match(r"^  \S", line)
        if block == "ota" and re.match(r"^\s+(encryption|password):", line):
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def secret_values():
    try:
        vals = {}
        for line in open(SECRETS_YAML, encoding="utf-8"):
            m = re.match(r"^([A-Za-z0-9_]+):\s*\"?([^\"#\n]+?)\"?\s*$", line)
            if m and len(m.group(2)) >= 6:
                vals[m.group(1)] = m.group(2)
        return vals
    except OSError:
        return {}


def esphome_parts(fw, dest):
    src = fw["source"]
    original = open(os.path.normpath(os.path.join(ROOT, src["yaml"])), encoding="utf-8").read()
    if re.search(r"!include|^packages:|^external_components:", original, re.M):
        sys.exit(f"{fw['id']}: ESPHome-kilden henter andre filer - den kan ikke bygges som en generisk kopi")
    # The generic copy is compiled in its own folder (kept for the build cache), never next to the original
    work = os.path.join(ROOT, ".esphome", "work", fw["id"])
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, f"{src['name']}.yaml"), "w", encoding="utf-8") as f:
        f.write(generic_yaml(original))
    subprocess.run([ESPHOME, "compile", f"{src['name']}.yaml"], cwd=work, check=True, stdout=subprocess.DEVNULL)
    factory = os.path.join(work, ".esphome", "build", src["name"], "build", "firmware.factory.bin")
    data = open(factory, "rb").read()
    leaks = [k for k, v in secret_values().items() if v.encode() in data]
    m = re.search(r"key:\s*\"([A-Za-z0-9+/=]{40,})\"", original)
    if m and m.group(1).encode() in data:
        leaks.append("api-nøglen")
    if leaks:
        sys.exit(f"{fw['id']}: firmwaren indeholder {', '.join(leaks)} - stopper")
    shutil.copy2(factory, os.path.join(dest, "firmware.factory.bin"))
    m = re.search(r'^\s+version:\s*"?([^"\n]+)"?', original, re.M)
    built = datetime.datetime.fromtimestamp(os.path.getmtime(factory)).strftime("%Y-%m-%d")
    return fw["chip"], m.group(1) if m else "0", built, [{"path": "firmware.factory.bin", "offset": 0}], {
        "home_assistant_domain": "esphome"}


def url_parts(fw, dest):
    url = fw["source"]["url"]
    manifest = json.load(urllib.request.urlopen(url, timeout=30))
    build = manifest["builds"][0]
    parts = []
    for p in build["parts"]:
        name = os.path.basename(p["path"])
        with urllib.request.urlopen(urllib.parse.urljoin(url, p["path"]), timeout=120) as r, open(os.path.join(dest, name), "wb") as f:
            shutil.copyfileobj(r, f)
        parts.append({"path": name, "offset": p["offset"]})
    extra = {k: manifest[k] for k in ("home_assistant_domain", "funding_url") if k in manifest}
    return build["chipFamily"], manifest.get("version", "0"), datetime.date.today().isoformat(), parts, extra


def main():
    cfg = json.load(open(os.path.join(ROOT, "firmwares.json"), encoding="utf-8"))
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    catalog = []
    for fw in cfg["firmwares"]:
        dest = os.path.join(OUT, fw["id"])
        os.makedirs(dest)
        kind = fw["source"]["type"]
        chip, version, built, parts, extra = {"idf": idf_parts, "esphome": esphome_parts}.get(kind, url_parts)(fw, dest)
        manifest = {
            "name": fw["name"],
            "version": version,
            # The user picks "Erase device" in the dialog; without it NVS and the Zigbee pairing stay.
            "new_install_prompt_erase": True,
            **extra,
            "builds": [{"chipFamily": chip, "parts": parts}],
        }
        json.dump(manifest, open(os.path.join(dest, "manifest.json"), "w"), indent=2)
        sha = hashlib.sha256()
        for p in parts:
            sha.update(open(os.path.join(dest, p["path"]), "rb").read())
        entry = {k: v for k, v in fw.items() if k != "source"}
        entry.update(version=version, date=built, manifest=f"{fw['id']}/manifest.json", sha256=sha.hexdigest()[:12])
        catalog.append(entry)
        print(f"{fw['id']:22} {chip:9} v{version:12} {built}  {', '.join(p['path'] for p in parts)}")
    json.dump({"generated": datetime.datetime.now().isoformat(timespec="seconds"), "firmwares": catalog},
              open(os.path.join(OUT, "catalog.json"), "w"), ensure_ascii=False, indent=2)

    if "--upload" not in sys.argv:
        return
    if not CFG.get("host"):
        sys.exit("Upload kræver tools/config.local.json (se config.example.json)")
    host, remote = CFG["host"], CFG.get("appdata", "/mnt/user/appdata/esp-flasher").rstrip("/") + "/firmware"
    key = tempfile.mktemp()
    shutil.copy(os.path.expanduser(CFG["ssh_key"]), key)
    os.chmod(key, 0o600)
    try:
        ssh = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no", host]
        # Upload next to the live folder, then swap, so the page never sees a half-copied catalog. ".local" makes the
        # container serve this folder instead of the firmware built into the image.
        tar = subprocess.Popen(["tar", "-C", os.path.dirname(OUT), "-cf", "-", "firmware"], stdout=subprocess.PIPE)
        subprocess.run(ssh + [f"set -e; mkdir -p {remote}.new && rm -rf {remote}.new/* && tar -C {remote}.new --strip-components=1 -xf - "
                              f"&& touch {remote}.new/.local && chmod -R a+rX {remote}.new && rm -rf {remote}.old "
                              f"&& (mv {remote} {remote}.old 2>/dev/null || true) && mv {remote}.new {remote} && rm -rf {remote}.old"],
                       stdin=tar.stdout, check=True)
        tar.wait()
        print(f"Uploaded to {host}:{remote} (.local)")
    finally:
        os.remove(key)


if __name__ == "__main__":
    main()
