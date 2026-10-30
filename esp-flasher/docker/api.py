#!/usr/bin/env python3
"""ESP Flasher API: first-run setup, admin login and the installation's own settings (Claude AI, 2026-10-30).

Nothing personal is built into the image. On the first visit the page asks for a name, an admin code, the Wi-Fi the
devices should join and the address(es) the flasher is opened on. They are stored on the data volume:

  /config/settings.json   name, addresses, Home Assistant link (not secret, shown on the page)
  /config/secrets.json    admin code (PBKDF2 hash), Wi-Fi name/password, session key - mode 600, never served by nginx

As a Home Assistant app (FLASHER_MODE=ha) there is no setup page or admin code: Home Assistant's login protects
the page (Ingress), and name/Wi-Fi come from the app's Configuration tab (/data/options.json, kept by the Supervisor).

Runs on 127.0.0.1:8081 behind nginx (/api/). Python standard library only.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import fwsync

CONFIG = os.environ.get("FLASHER_CONFIG", "/config")
SETTINGS = os.path.join(CONFIG, "settings.json")
SECRETS = os.path.join(CONFIG, "secrets.json")
VERSION = os.environ.get("FLASHER_VERSION", "dev")
HA_MODE = os.environ.get("FLASHER_MODE") == "ha"
HA_OPTIONS = os.environ.get("FLASHER_HA_OPTIONS", "/data/options.json")
HA_ONLY = "Indstillingerne laves i Home Assistant: Indstillinger → Apps → ESP Flasher → Konfiguration"
SESSION_DAYS = 30
PBKDF2_ROUNDS = 240_000
_lock = threading.Lock()
_fails = {}   # ip -> [count, first_failure_time]


# ---------- storage ----------------------------------------------------------------------------------------------
def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data, mode):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def ha_options():
    return _read(HA_OPTIONS, {})


_ha_cfg = {"t": 0, "data": {}}


def ha_core_config():
    """external/internal URL of Home Assistant (via the Supervisor), so the page can offer the https address."""
    if time.time() - _ha_cfg["t"] < 300:
        return _ha_cfg["data"]
    data = {}
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        try:
            import urllib.request
            req = urllib.request.Request("http://supervisor/core/api/config", headers={"Authorization": f"Bearer {token}"})
            cfg = json.load(urllib.request.urlopen(req, timeout=5))
            data = {"external_url": cfg.get("external_url") or "", "internal_url": cfg.get("internal_url") or ""}
        except Exception as err:   # noqa: BLE001 - only a hint for the page
            print("HA-konfiguration:", err, flush=True)
    _ha_cfg.update(t=time.time(), data=data)
    return data


def settings():
    if HA_MODE:
        o = ha_options()
        return {"name": o.get("name") or "Home Assistant", "hosts": [], "ha_url": "", **ha_core_config()}
    return _read(SETTINGS, {})


def secret_store():
    if HA_MODE:
        o = ha_options()
        return {"admin_hash": "ha", "wifi_ssid": o.get("wifi_ssid", ""), "wifi_password": o.get("wifi_password", "")}
    return _read(SECRETS, {})


def firmware_url():
    """Where new firmware is fetched from: the public catalog on GitHub unless turned off."""
    if HA_MODE:
        return fwsync.DEFAULT_URL if ha_options().get("live_firmware", True) else ""
    url = os.environ.get("FLASHER_FIRMWARE_URL", fwsync.DEFAULT_URL).strip()
    return "" if url.lower() in ("", "off", "0", "false", "no") else url


def firmware_status():
    st = fwsync.state
    return {"source": st["source"], "live": st["live"], "generated": st["generated"], "error": st["error"],
            "checked": int(st["checked"]), "changed": int(st["changed"])}


def setup_done():
    return HA_MODE or bool(secret_store().get("admin_hash"))


# ---------- admin code + sessions --------------------------------------------------------------------------------
def hash_code(code, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_code(code, stored):
    try:
        _, rounds, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", code.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(test, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def make_session(sec):
    exp = int(time.time()) + SESSION_DAYS * 86400
    body = f"{exp}.{secrets.token_urlsafe(12)}"
    sig = hmac.new(sec["session_key"].encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def valid_session(token, sec):
    try:
        exp, rnd, sig = token.split(".")
        good = hmac.new(sec["session_key"].encode(), f"{exp}.{rnd}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good) and int(exp) > time.time()
    except (ValueError, KeyError, AttributeError):
        return False


# ---------- validation -------------------------------------------------------------------------------------------
HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


def clean_hosts(values):
    out = []
    for v in values or []:
        v = str(v).strip().lower()
        if not v:
            continue
        try:
            ipaddress.ip_address(v)
        except ValueError:
            if not HOST_RE.match(v):
                raise ValueError(f"Ugyldig adresse: {v}")
        if v not in out:
            out.append(v)
    if len(out) > 8:
        raise ValueError("Højst 8 adresser")
    return out


def clean_url(v):
    v = str(v or "").strip()
    if v and not re.match(r"^https?://[^\s/]+(:\d+)?(/.*)?$", v):
        raise ValueError("Home Assistant-adressen skal starte med http:// eller https://")
    return v.rstrip("/")


def text(v, field, maxlen, required=False):
    v = str(v or "").strip()
    if required and not v:
        raise ValueError(f"{field} mangler")
    if len(v) > maxlen:
        raise ValueError(f"{field} er for lang (højst {maxlen} tegn)")
    return v


def issue_certificate():
    """Reissue the server certificate for the saved addresses and reload nginx (no restart needed)."""
    try:
        subprocess.run(["sh", "/app/certs.sh"], check=True, capture_output=True, timeout=60)
        subprocess.run(["nginx", "-c", "/tmp/nginx.conf", "-s", "reload"], check=False, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as err:
        print("certifikat:", err, flush=True)


# ---------- HTTP -------------------------------------------------------------------------------------------------
class Api(BaseHTTPRequestHandler):
    server_version = "esp-flasher-api"

    def log_message(self, fmt, *args):   # quiet; nginx has the access log turned off as well
        pass

    # helpers
    def client_ip(self):
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 16384:
            raise ValueError("For stor forespørgsel")
        if not n:
            return {}
        data = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("Forventede et JSON-objekt")
        return data

    def send(self, status, data=None, cookie=None):
        raw = json.dumps(data if data is not None else {}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def session_cookie(self, token, max_age=SESSION_DAYS * 86400):
        return f"ef_session={token}; Path=/api; Max-Age={max_age}; HttpOnly; Secure; SameSite=Strict"

    def logged_in(self, sec):
        if HA_MODE:   # only reachable through Ingress, which already requires a Home Assistant login
            return True
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return "ef_session" in c and valid_session(c["ef_session"].value, sec)

    def require_login(self, sec):
        if not self.logged_in(sec):
            self.send(401, {"error": "Lås op med adminkoden først"})
            return False
        return True

    def throttled(self):
        ip = self.client_ip()
        count, first = _fails.get(ip, (0, 0))
        if time.time() - first > 900:
            _fails.pop(ip, None)
            return False
        return count >= 8

    def failed(self):
        ip = self.client_ip()
        count, first = _fails.get(ip, (0, time.time()))
        _fails[ip] = (count + 1, first)
        time.sleep(1.0)

    # routes
    def do_GET(self):
        sec = secret_store()
        st = settings()
        if self.path == "/api/status":
            return self.send(200, {
                "mode": "ha" if HA_MODE else "docker",
                "setup_done": setup_done(),
                "logged_in": bool(sec) and self.logged_in(sec),
                "name": st.get("name", ""),
                "ha_url": st.get("ha_url", ""),
                "external_url": st.get("external_url", ""),
                "hosts": st.get("hosts", []),
                "wifi_ssid": sec.get("wifi_ssid", "") if sec and self.logged_in(sec) else "",
                "has_wifi": bool(sec.get("wifi_ssid")),
                "version": VERSION,
                "firmware": firmware_status(),
            })
        if self.path == "/api/settings":
            if not self.require_login(sec):
                return
            return self.send(200, {**st, "wifi_ssid": sec.get("wifi_ssid", ""),
                                   "has_wifi_password": bool(sec.get("wifi_password"))})
        if self.path == "/api/wifi":
            if not self.require_login(sec):
                return
            return self.send(200, {"ssid": sec.get("wifi_ssid", ""), "password": sec.get("wifi_password", "")})
        self.send(404, {"error": "Ukendt adresse"})

    def do_POST(self):
        try:
            data = self.body()
        except ValueError as err:
            return self.send(400, {"error": str(err)})
        if self.path == "/api/firmware/check":   # harmless, so no login; at most one real check a minute
            changed = time.time() - fwsync.state["checked"] >= 60 and fwsync.check()
            return self.send(200, {**firmware_status(), "updated": bool(changed)})
        if HA_MODE and self.path in ("/api/setup", "/api/login", "/api/reset"):
            return self.send(409, {"error": HA_ONLY})
        with _lock:
            if self.path == "/api/setup":
                return self.api_setup(data)
            if self.path == "/api/login":
                return self.login(data)
            if self.path == "/api/logout":
                return self.send(200, {"ok": True}, cookie=self.session_cookie("", 0))
            if self.path == "/api/reset":
                return self.reset(data)
        self.send(404, {"error": "Ukendt adresse"})

    def do_PUT(self):
        try:
            data = self.body()
        except ValueError as err:
            return self.send(400, {"error": str(err)})
        if HA_MODE:
            return self.send(409, {"error": HA_ONLY})
        with _lock:
            if self.path == "/api/settings":
                return self.update(data)
        self.send(404, {"error": "Ukendt adresse"})

    def api_setup(self, data):
        if setup_done():
            return self.send(409, {"error": "Flasheren er allerede sat op"})
        try:
            code = str(data.get("admin_code") or "")
            if len(code) < 6:
                raise ValueError("Adminkoden skal være mindst 6 tegn")
            st = {
                "name": text(data.get("name"), "Navn", 60, required=True),
                "hosts": clean_hosts(data.get("hosts")),
                "ha_url": clean_url(data.get("ha_url")),
                "created": time.strftime("%Y-%m-%d"),
            }
            sec = {
                "admin_hash": hash_code(code),
                "session_key": secrets.token_hex(32),
                "wifi_ssid": text(data.get("wifi_ssid"), "Wi-Fi-navn", 32),
                "wifi_password": text(data.get("wifi_password"), "Wi-Fi-kode", 64),
            }
        except ValueError as err:
            return self.send(400, {"error": str(err)})
        _write(SECRETS, sec, 0o600)
        _write(SETTINGS, st, 0o644)
        threading.Thread(target=issue_certificate, daemon=True).start()
        self.send(200, {"ok": True}, cookie=self.session_cookie(make_session(sec)))

    def login(self, data):
        sec = secret_store()
        if not sec.get("admin_hash"):
            return self.send(409, {"error": "Flasheren er ikke sat op endnu"})
        if self.throttled():
            return self.send(429, {"error": "For mange forsøg – vent 15 minutter"})
        if not check_code(str(data.get("admin_code") or ""), sec["admin_hash"]):
            self.failed()
            return self.send(403, {"error": "Forkert adminkode"})
        _fails.pop(self.client_ip(), None)
        self.send(200, {"ok": True}, cookie=self.session_cookie(make_session(sec)))

    def update(self, data):
        sec = secret_store()
        if not self.require_login(sec):
            return
        st = settings()
        old_hosts = st.get("hosts", [])
        try:
            if "name" in data:
                st["name"] = text(data["name"], "Navn", 60, required=True)
            if "hosts" in data:
                st["hosts"] = clean_hosts(data["hosts"])
            if "ha_url" in data:
                st["ha_url"] = clean_url(data["ha_url"])
            if "wifi_ssid" in data:
                sec["wifi_ssid"] = text(data["wifi_ssid"], "Wi-Fi-navn", 32)
            if data.get("wifi_password"):   # empty = keep the saved one
                sec["wifi_password"] = text(data["wifi_password"], "Wi-Fi-kode", 64)
            if data.get("clear_wifi_password"):
                sec["wifi_password"] = ""
            if data.get("new_admin_code"):
                if not check_code(str(data.get("admin_code") or ""), sec["admin_hash"]):
                    raise ValueError("Den nuværende adminkode er forkert")
                if len(str(data["new_admin_code"])) < 6:
                    raise ValueError("Den nye adminkode skal være mindst 6 tegn")
                sec["admin_hash"] = hash_code(str(data["new_admin_code"]))
                sec["session_key"] = secrets.token_hex(32)   # signs everyone else out
        except ValueError as err:
            return self.send(400, {"error": str(err)})
        _write(SECRETS, sec, 0o600)
        _write(SETTINGS, st, 0o644)
        if st.get("hosts") != old_hosts:
            threading.Thread(target=issue_certificate, daemon=True).start()
        cookie = self.session_cookie(make_session(sec)) if data.get("new_admin_code") else None
        self.send(200, {"ok": True}, cookie=cookie)

    def reset(self, data):
        sec = secret_store()
        if not self.require_login(sec):
            return
        if not check_code(str(data.get("admin_code") or ""), sec["admin_hash"]):
            self.failed()
            return self.send(403, {"error": "Forkert adminkode"})
        for p in (SECRETS, SETTINGS):
            try:
                os.remove(p)
            except OSError:
                pass
        self.send(200, {"ok": True}, cookie=self.session_cookie("", 0))


if __name__ == "__main__":
    os.makedirs(CONFIG, exist_ok=True)
    fwsync.start(firmware_url(), local_override=os.environ.get("FLASHER_FW_LOCAL") == "1")
    port = int(os.environ.get("FLASHER_API_PORT", "8081"))
    ThreadingHTTPServer(("127.0.0.1", port), Api).serve_forever()
