"""Live firmware (Claude AI, 2026-10-30): keeps the served firmware in step with the catalog on GitHub, so a new
firmware shows up without updating the app or the container.

nginx serves /firmware/ through the symlink /tmp/fw. It points to the firmware built into the image (/app/firmware)
until a newer catalog has been mirrored into <config>/fw-live/<generation>. The switch is one atomic symlink swap, so
the page never sees half a catalog, and every part is checked against the catalog's sha256 before it is used.
Unchanged firmwares are copied from the generation in use instead of being downloaded again.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.request

CONFIG = os.environ.get("FLASHER_CONFIG", "/config")
BUNDLED = os.environ.get("FLASHER_FW_BUNDLED", "/app/firmware")
LINK = os.environ.get("FLASHER_FW_LINK", "/tmp/fw")
LIVE = os.path.join(CONFIG, "fw-live")
DEFAULT_URL = "https://raw.githubusercontent.com/MRDonnii/esp-flasher/main/esp-flasher/firmware/"
INTERVAL = 30 * 60      # normal check
RETRY = 5 * 60          # after a failed check
MAX_CATALOG = 1 << 20
MAX_PART = 16 << 20
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

state = {"source": "app", "live": False, "generated": "", "checked": 0, "changed": 0, "error": ""}
_lock = threading.Lock()
_url = ""


def _catalog(folder):
    try:
        with open(os.path.join(folder, "catalog.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data.get("firmwares"), list) else None
    except (OSError, ValueError, AttributeError):
        return None


def _get(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": "esp-flasher", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{url.rsplit('/', 1)[-1]} er for stor")
    return data


def _point(folder):
    tmp = LINK + ".new"
    try:
        os.remove(tmp)
    except OSError:
        pass
    os.symlink(folder, tmp)
    os.replace(tmp, LINK)


def _content(cat):
    """Catalog without its timestamp: equal means nothing to do."""
    return json.dumps({k: v for k, v in (cat or {}).items() if k != "generated"}, sort_keys=True)


def _mirror_one(fw, remote_base, new_dir, cur_dir, cur_by_id):
    fid = fw.get("id", "")
    manifest_rel = fw.get("manifest", "")
    if not SAFE_ID.match(fid) or manifest_rel != f"{fid}/manifest.json" or not re.match(r"^[0-9a-f]{12}$", fw.get("sha256", "")):
        raise ValueError(f"Ugyldig post i kataloget: {fid or '?'}")
    dest = os.path.join(new_dir, fid)
    old = cur_by_id.get(fid)
    if old and old.get("sha256") == fw["sha256"] and os.path.isfile(os.path.join(cur_dir, manifest_rel)):
        shutil.copytree(os.path.join(cur_dir, fid), dest)   # unchanged: reuse what we have
        return False
    os.makedirs(dest)
    raw = _get(remote_base + manifest_rel, MAX_CATALOG)
    manifest = json.loads(raw)
    sha = hashlib.sha256()
    for part in manifest["builds"][0]["parts"]:
        name = part["path"]
        if not SAFE_FILE.match(name):
            raise ValueError(f"{fid}: ugyldigt filnavn {name!r}")
        data = _get(f"{remote_base}{fid}/{name}", MAX_PART)
        sha.update(data)
        with open(os.path.join(dest, name), "wb") as f:
            f.write(data)
    if sha.hexdigest()[:12] != fw["sha256"]:
        raise ValueError(f"{fid}: kontrolsummen passer ikke - springer opdateringen over")
    with open(os.path.join(dest, "manifest.json"), "wb") as f:
        f.write(raw)
    return True


def check():
    """One check against GitHub. Returns True when a new catalog went live."""
    if not _url:
        return False
    with _lock:
        state["checked"] = time.time()
        new_dir = None
        try:
            remote = json.loads(_get(_url + "catalog.json", MAX_CATALOG))
            if not isinstance(remote.get("firmwares"), list):
                raise ValueError("Kataloget på GitHub er ugyldigt")
            cur_dir = os.path.realpath(LINK)
            cur = _catalog(cur_dir) or {"firmwares": []}
            if _content(remote) == _content(cur) or str(remote.get("generated", "")) < str(cur.get("generated", "")):
                state["error"] = ""
                return False
            os.makedirs(LIVE, exist_ok=True)
            new_dir = tempfile.mkdtemp(prefix="g" + time.strftime("%Y%m%d-%H%M%S-"), dir=LIVE)   # always a new name
            os.chmod(new_dir, 0o755)   # nginx reads it as its own user
            cur_by_id = {f.get("id"): f for f in cur["firmwares"]}
            fetched = [f["id"] for f in remote["firmwares"] if _mirror_one(f, _url, new_dir, cur_dir, cur_by_id)]
            with open(os.path.join(new_dir, "catalog.json"), "w", encoding="utf-8") as f:
                json.dump(remote, f, ensure_ascii=False, indent=2)
            _point(new_dir)
            new_dir = None
            # keep the previous generation (a browser may still be downloading from it), drop older ones
            keep = {os.path.realpath(LINK), cur_dir}
            for name in os.listdir(LIVE):
                path = os.path.join(LIVE, name)
                if os.path.realpath(path) not in keep:
                    shutil.rmtree(path, ignore_errors=True)
            state.update(source="github", generated=str(remote.get("generated", "")), changed=time.time(), error="")
            print(f"Ny firmware fra GitHub ({remote.get('generated')}): {', '.join(fetched) or 'kun tekster'}", flush=True)
            return True
        except Exception as err:   # noqa: BLE001 - any failure keeps the firmware we already serve
            state["error"] = str(err)[:200]
            print("Firmware-tjek:", err, flush=True)
            return False
        finally:
            if new_dir:
                shutil.rmtree(new_dir, ignore_errors=True)


def _loop():
    time.sleep(15)   # let the network come up
    while True:
        check()
        time.sleep(RETRY if state["error"] else INTERVAL)


def start(url, local_override=False):
    """Pick the newest firmware we have (image or an earlier mirror) and keep it up to date from `url`."""
    global _url
    if local_override:   # a maintainer serves their own builds from <config>/firmware (.local)
        state.update(source="local", generated=str((_catalog(os.path.realpath(LINK)) or {}).get("generated", "")))
        return
    best, best_cat = BUNDLED, _catalog(BUNDLED) or {}
    if os.path.isdir(LIVE):
        for name in sorted(os.listdir(LIVE)):
            cat = _catalog(os.path.join(LIVE, name))
            if cat and str(cat.get("generated", "")) > str(best_cat.get("generated", "")):
                best, best_cat = os.path.join(LIVE, name), cat
    _point(best)
    state.update(source="app" if best == BUNDLED else "github", generated=str(best_cat.get("generated", "")))
    _url = url.rstrip("/") + "/" if url else ""
    state["live"] = bool(_url)
    if _url:
        threading.Thread(target=_loop, daemon=True).start()
