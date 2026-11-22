"""Profile catalogs (Claude AI, 2026-11-22): ESP Flasher ships with no firmware of its own. Whoever runs it adds one or
more profile catalogs (an address, plus a read-only token for a private GitHub repo), and this module keeps a local
mirror of them, so a new profile shows up without updating the app or the container.

Everything is fetched here, on the server: the browser only talks to this flasher, so a catalog needs no CORS and a
token never reaches the browser. A private GitHub repo is read through the GitHub API (fine-grained token with
"Contents: read" for that one repo): one tree listing per check, then each file as a git blob. (The contents API is
not used: it re-encodes binaries it takes for text, e.g. an otadata file of only 0xFF bytes.) A token is only sent to
the host it belongs to, never along a redirect elsewhere.

nginx serves /firmware/ through the symlink /tmp/fw. It points to an empty catalog until the configured catalogs have
been mirrored into <config>/fw-live/<generation>. The switch is one atomic symlink swap, so the page never sees half a
catalog, and every part is checked against the catalog's sha256 before it is used. Unchanged profiles are copied from
the generation in use instead of being downloaded again. A generation belongs to one set of catalog addresses: change
the set (or remove every catalog) and the old profiles are no longer served.

Catalog format (the same as Fleetdeck's ESP-flash reads): <base>/catalog.json = {"generated": "<ISO time>",
"firmwares": [{"id", "name", "chip", "manifest": "<id>/manifest.json", "sha256": "<first 12 hex of SHA-256 over the
parts in order>", ...}]}; <base>/<id>/manifest.json is an ESP Web Tools manifest whose parts are plain file names in
<base>/<id>/. See the README.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIG = os.environ.get("FLASHER_CONFIG", "/config")
LINK = os.environ.get("FLASHER_FW_LINK", "/tmp/fw")
EMPTY = os.environ.get("FLASHER_FW_EMPTY", "/tmp/fw-empty")
LIVE = os.path.join(CONFIG, "fw-live")
INTERVAL = 30 * 60      # normal check
RETRY = 5 * 60          # after a failed check
MAX_CATALOG = 1 << 20
MAX_PART = 16 << 20
MAX_SOURCES = 5
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{10,255}$")

state = {"source": "none", "live": False, "generated": "", "checked": 0, "changed": 0, "error": "", "catalogs": []}
_lock = threading.Lock()
_sources = []          # [{"url": base ending in "/", "token": str}]
_thread = None
_trees = {}            # during one check: catalog address -> {path in the repo: blob sha} (GitHub with a token)


# ---------- catalog addresses -------------------------------------------------------------------------------------
def normalize_url(url):
    """A catalog address as a base URL ending in "/". Takes the folder, its catalog.json, or a GitHub address
    (https://github.com/OWNER/REPO[/tree/BRANCH[/folder]]). Raises ValueError for anything else."""
    url = str(url or "").strip()
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("https", "http") or not u.hostname or u.query or u.fragment or u.username or u.password:
        raise ValueError(f"Ugyldig katalog-adresse: {url or '(tom)'} – den skal starte med https://")
    if u.hostname == "github.com":
        bits = [b for b in u.path.split("/") if b]
        if len(bits) == 2:
            bits += ["main"]
        elif len(bits) >= 4 and bits[2] in ("tree", "blob"):
            bits = bits[:2] + bits[3:]
        else:
            raise ValueError(f"Ugyldig GitHub-adresse: {url} – brug https://github.com/EJER/REPO/tree/main/mappe")
        bits[1] = bits[1].removesuffix(".git")
        u = urllib.parse.urlsplit("https://raw.githubusercontent.com/" + "/".join(bits))
    path = u.path
    if path.endswith("/catalog.json"):
        path = path[: -len("catalog.json")]
    if not path.endswith("/"):
        path += "/"
    return urllib.parse.urlunsplit((u.scheme, u.netloc, path, "", ""))


def label(base):
    """A short name for a catalog address, for the page and the log."""
    u = urllib.parse.urlsplit(base)
    if u.hostname == "raw.githubusercontent.com":
        bits = [b for b in u.path.split("/") if b]
        if len(bits) >= 3:
            return f"github.com/{bits[0]}/{bits[1]}" + ("/" + "/".join(bits[3:]) if len(bits) > 3 else "") + \
                ("" if bits[2] == "main" else f" ({bits[2]})")
    return (u.netloc + u.path).rstrip("/")


def _fingerprint(sources):
    """Which catalogs a generation was built from (addresses only, never tokens)."""
    return hashlib.sha256("\n".join(s["url"] for s in sources).encode()).hexdigest()[:16]


def clean_sources(items):
    """[{"url", "token"}] from the configuration, normalized. Raises ValueError on a bad address or token."""
    out = []
    for item in items or []:
        if not isinstance(item, dict) or not str(item.get("url") or "").strip():
            continue
        url = normalize_url(item.get("url"))
        token = str(item.get("token") or "").strip()
        if token and not TOKEN_RE.match(token):
            raise ValueError(f"Tokenet til {label(url)} har ugyldige tegn")
        if url not in [s["url"] for s in out]:
            out.append({"url": url, "token": token})
    if len(out) > MAX_SOURCES:
        raise ValueError(f"Højst {MAX_SOURCES} kataloger")
    return out


# ---------- fetching ----------------------------------------------------------------------------------------------
class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but drop the token as soon as one leaves the host it was meant for."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_opener = urllib.request.build_opener(_SameHostRedirects)


def _open(req, limit):
    with _opener.open(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{req.full_url.rsplit('/', 1)[-1].split('?')[0]} er for stor")
    return data


def _github(source, rel):
    """A private GitHub repo through the API: the blob for <folder>/<rel>, looked up in the repo's tree."""
    owner, repo, ref, *folder = [b for b in urllib.parse.urlsplit(source["url"]).path.split("/") if b]
    q = urllib.parse.quote
    api = f"https://api.github.com/repos/{q(owner)}/{q(repo)}"
    headers = {"User-Agent": "esp-flasher", "Authorization": f"Bearer {source['token']}",
               "X-GitHub-Api-Version": "2022-11-28"}
    if source["url"] not in _trees:
        raw = _open(urllib.request.Request(f"{api}/git/trees/{q(ref, safe='')}?recursive=1",
                                           headers={**headers, "Accept": "application/vnd.github+json"}), 16 << 20)
        _trees[source["url"]] = {t["path"]: t["sha"] for t in json.loads(raw).get("tree", []) if t.get("type") == "blob"}
    sha = _trees[source["url"]].get("/".join(folder + [rel]))
    if not sha:
        raise urllib.error.HTTPError(f"{api}/{rel}", 404, "Not Found", None, None)
    return urllib.request.Request(f"{api}/git/blobs/{sha}", headers={**headers, "Accept": "application/vnd.github.raw"})


def _request(source, rel):
    """The request for a file in a catalog. With a token, a GitHub repo is read through the GitHub API (it takes
    fine-grained tokens); other hosts get the token as a Bearer header. Without a token the file is fetched as it is."""
    base, token = source["url"], source.get("token", "")
    if token and urllib.parse.urlsplit(base).hostname == "raw.githubusercontent.com":
        return _github(source, rel)
    headers = {"User-Agent": "esp-flasher", "Cache-Control": "no-cache"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(base + rel, headers=headers)


def _get(source, rel, limit):
    try:
        data = _open(_request(source, rel), limit)
    except urllib.error.HTTPError as err:
        why = {401: "tokenet blev afvist", 403: "ingen adgang (tokenet eller GitHubs grænse)",
               404: "findes ikke – eller repoet er privat og tokenet mangler"}.get(err.code, err.reason)
        raise ValueError(f"{label(source['url'])}: {rel} – {err.code} {why}") from None
    except (urllib.error.URLError, OSError) as err:
        raise ValueError(f"{label(source['url'])}: {getattr(err, 'reason', err)}") from None
    except ValueError as err:
        raise ValueError(f"{label(source['url'])}: {err}") from None
    return data


# ---------- the served folder -------------------------------------------------------------------------------------
def _catalog(folder):
    try:
        with open(os.path.join(folder, "catalog.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data.get("firmwares"), list) else None
    except (OSError, ValueError, AttributeError):
        return None


def _point(folder):
    tmp = LINK + ".new"
    try:
        os.remove(tmp)
    except OSError:
        pass
    os.symlink(folder, tmp)
    os.replace(tmp, LINK)


def _empty():
    os.makedirs(EMPTY, exist_ok=True)
    os.chmod(EMPTY, 0o755)
    with open(os.path.join(EMPTY, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": "", "firmwares": []}, f)
    return EMPTY


def _content(cat):
    """Catalog without its timestamp: equal means nothing to do."""
    return json.dumps({k: v for k, v in (cat or {}).items() if k != "generated"}, sort_keys=True)


def _mirror_one(fw, source, new_dir, cur_dir, cur_by_id):
    fid = fw.get("id", "")
    manifest_rel = fw.get("manifest", "")
    if not SAFE_ID.match(fid) or manifest_rel != f"{fid}/manifest.json" or not re.match(r"^[0-9a-f]{12}$", fw.get("sha256", "")):
        raise ValueError(f"Ugyldig post i kataloget {label(source['url'])}: {fid or '?'}")
    dest = os.path.join(new_dir, fid)
    old = cur_by_id.get(fid)
    if old and old.get("sha256") == fw["sha256"] and os.path.isfile(os.path.join(cur_dir, manifest_rel)):
        shutil.copytree(os.path.join(cur_dir, fid), dest)   # unchanged: reuse what we have
        return False
    os.makedirs(dest)
    raw = _get(source, manifest_rel, MAX_CATALOG)
    manifest = json.loads(raw)
    sha = hashlib.sha256()
    for part in manifest["builds"][0]["parts"]:
        name = part["path"]
        if not SAFE_FILE.match(name):
            raise ValueError(f"{fid}: ugyldigt filnavn {name!r}")
        data = _get(source, f"{fid}/{name}", MAX_PART)
        sha.update(data)
        with open(os.path.join(dest, name), "wb") as f:
            f.write(data)
    if sha.hexdigest()[:12] != fw["sha256"]:
        raise ValueError(f"{fid}: kontrolsummen passer ikke - springer opdateringen over")
    with open(os.path.join(dest, "manifest.json"), "wb") as f:
        f.write(raw)
    return True


def _merged(sources):
    """All configured catalogs as one list; the first catalog with an id wins it."""
    entries, seen, generated = [], set(), ""
    for src in sources:
        cat = json.loads(_get(src, "catalog.json", MAX_CATALOG))
        if not isinstance(cat, dict) or not isinstance(cat.get("firmwares"), list):
            raise ValueError(f"{label(src['url'])}: catalog.json er ikke et profil-katalog")
        generated = max(generated, str(cat.get("generated", "")))
        for fw in cat["firmwares"]:
            if isinstance(fw, dict) and fw.get("id") not in seen:
                seen.add(fw.get("id"))
                entries.append((src, fw))
    return generated, entries


def check():
    """One check of the configured catalogs. Returns True when a new catalog went live."""
    if not _sources:
        return False
    with _lock:
        state["checked"] = time.time()
        new_dir = None
        _trees.clear()   # a fresh listing of each GitHub repo per check
        try:
            sources = list(_sources)
            generated, entries = _merged(sources)
            remote = {"generated": generated, "sources": _fingerprint(sources), "firmwares": [fw for _, fw in entries]}
            cur_dir = os.path.realpath(LINK)
            cur = _catalog(cur_dir) or {"firmwares": []}
            if _content(remote) == _content(cur):
                state["error"] = ""
                return False
            os.makedirs(LIVE, exist_ok=True)
            new_dir = tempfile.mkdtemp(prefix="g" + time.strftime("%Y%m%d-%H%M%S-"), dir=LIVE)   # always a new name
            os.chmod(new_dir, 0o755)   # nginx reads it as its own user
            cur_by_id = {f.get("id"): f for f in cur["firmwares"]}
            fetched = [fw["id"] for src, fw in entries if _mirror_one(fw, src, new_dir, cur_dir, cur_by_id)]
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
            state.update(source="catalog", generated=generated, changed=time.time(), error="")
            print(f"Nye profiler ({generated}): {', '.join(fetched) or 'kun tekster'}", flush=True)
            return True
        except Exception as err:   # noqa: BLE001 - any failure keeps the profiles we already serve
            state["error"] = str(err)[:200]
            print("Profil-tjek:", err, flush=True)
            return False
        finally:
            if new_dir:
                shutil.rmtree(new_dir, ignore_errors=True)


def _loop():
    time.sleep(15)   # let the network come up
    while True:
        check()
        time.sleep(RETRY if state["error"] else INTERVAL)


def configure(sources):
    """Use these (cleaned) catalogs from now on. Another set of addresses starts from an empty list until mirrored."""
    global _sources, _thread
    sources = list(sources)
    changed = [s["url"] for s in sources] != [s["url"] for s in _sources]
    _sources = sources
    state.update(live=bool(sources), catalogs=[label(s["url"]) for s in sources])
    if not sources:
        state["error"] = ""
    if (_catalog(os.path.realpath(LINK)) or {}).get("sources") != (_fingerprint(sources) if sources else None):
        _point(_empty())
        state.update(source="none", generated="")
    if sources and _thread is None:
        _thread = threading.Thread(target=_loop, daemon=True)
        _thread.start()
    elif sources and changed:
        threading.Thread(target=check, daemon=True).start()


def start(sources, local_override=False):
    """Serve the newest mirror of exactly these catalogs (or an empty list), and keep it up to date."""
    if local_override:   # a maintainer serves their own builds from <config>/firmware (.local)
        state.update(source="local", generated=str((_catalog(os.path.realpath(LINK)) or {}).get("generated", "")))
        return
    fp = _fingerprint(sources) if sources else None
    best, best_cat = None, None
    gens = [os.path.join(LIVE, n) for n in sorted(os.listdir(LIVE))] if os.path.isdir(LIVE) else []
    for path in gens:
        cat = _catalog(path)
        if fp and cat and cat.get("sources") == fp and (best_cat is None or str(cat.get("generated", "")) >= str(best_cat.get("generated", ""))):
            best, best_cat = path, cat
    for path in gens:   # older generations, other catalogs, or firmware from an older version of the app
        if path != best:
            shutil.rmtree(path, ignore_errors=True)
    _point(best or _empty())
    state.update(source="catalog" if best else "none", generated=str((best_cat or {}).get("generated", "")))
    configure(sources)
