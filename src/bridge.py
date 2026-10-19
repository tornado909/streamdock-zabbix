"""Local, read-only Zabbix API bridge for a StreamDock item-widget plugin.

Python 3.9+, Windows, standard library only. Secrets are encrypted with Windows
DPAPI under the current Windows user profile. The HTTP API listens on loopback.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import ssl
import sys
from threading import RLock, Thread
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request

from universal import Catalog
from universal_http import handler_factory


APP = Path(__file__).resolve().parent
SETTINGS = APP / "settings.json"
SECRETS = APP / "credentials.dpapi"
HOST = "127.0.0.1"
PORT = 18398
VERSION = "1.0.0"

LOG = logging.getLogger("streamdock_zabbix")
CATALOG = Catalog()
CONNECTION = {"connected": False, "last_success": 0, "error": "Not checked yet"}
CONNECTION_LOCK = RLock()


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def protect_bytes(content, encrypt):
    """Encrypt/decrypt using Windows CurrentUser DPAPI, without extra dependencies."""
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is required")
    if not isinstance(content, bytes):
        raise TypeError("DPAPI input must be bytes")
    original = ctypes.create_string_buffer(content, len(content))
    incoming = DataBlob(len(content), ctypes.cast(original, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = DataBlob()
    fn = (ctypes.windll.crypt32.CryptProtectData if encrypt
          else ctypes.windll.crypt32.CryptUnprotectData)
    if not fn(ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def config():
    if not SETTINGS.is_file():
        raise RuntimeError("Missing settings.json; run install.ps1")
    raw = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise RuntimeError("settings.json must contain a JSON object")
    return raw


def validate_url(value):
    base = str(value or "").strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Set a valid http(s) Zabbix URL in settings.json")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Credentials and query strings are not allowed in Zabbix URL")
    if parsed.path.lower().endswith("/api_jsonrpc.php"):
        return base
    return base + "/api_jsonrpc.php"


class Auth:
    def __init__(self):
        self.lock = RLock()
        self.session = ""
        self.session_at = 0.0
        self.session_url = ""
        self.secrets_mtime = 0

    def invalidate(self):
        with self.lock:
            self.session = ""
            self.session_at = 0.0
            self.session_url = ""

    def credentials(self):
        if not SECRETS.is_file():
            raise RuntimeError("Zabbix credentials not configured. Run configure.ps1")
        decoded = json.loads(protect_bytes(SECRETS.read_bytes(), False).decode("utf-8"))
        if not isinstance(decoded, dict) or decoded.get("kind") not in ("login", "token"):
            raise RuntimeError("Invalid credentials file")
        return decoded

    def _login(self, endpoint, username, password):
        payload = {"jsonrpc": "2.0", "method": "user.login",
                   "params": {"username": username, "password": password}, "id": 1}
        request = urllib.request.Request(
            endpoint, json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json-rpc"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.load(response)
        if "error" in body:
            raise RuntimeError("Zabbix rejected the login")
        secret = body.get("result")
        if not isinstance(secret, str) or not secret:
            raise RuntimeError("Zabbix returned no session token")
        return secret

    def get(self):
        settings = config()
        endpoint = validate_url(settings.get("zabbix_url"))
        with self.lock:
            if not SECRETS.is_file():
                raise RuntimeError("Zabbix credentials not configured. Run configure.ps1")
            mtime = SECRETS.stat().st_mtime_ns
            if mtime != self.secrets_mtime or endpoint != self.session_url:
                self.session = ""
                self.secrets_mtime = mtime
            data = self.credentials()
            if data["kind"] == "token":
                return data["token"]
            if self.session and time.monotonic() - self.session_at < 1200:
                return self.session
            session = self._login(endpoint, data["username"], data["password"])
            self.session = session
            self.session_at = time.monotonic()
            self.session_url = endpoint
            return session

    def store(self, obj):
        data = protect_bytes(json.dumps(obj).encode("utf-8"), True)
        SECRETS.parent.mkdir(parents=True, exist_ok=True)
        temporary = SECRETS.with_suffix(".new")
        try:
            temporary.write_bytes(data)
            os.replace(str(temporary), str(SECRETS))
        finally:
            if temporary.exists():
                temporary.unlink()
        self.invalidate()


AUTH = Auth()


def api(url, secret, method, params, retry=True):
    request_data = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode("utf-8")
    request = urllib.request.Request(
        validate_url(url), request_data,
        {"Content-Type": "application/json-rpc",
         "Authorization": "Bearer " + secret,
         "User-Agent": "StreamDock-Zabbix/1.0"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        set_connection(False, "Cannot reach Zabbix")
        raise RuntimeError("Cannot reach Zabbix API")
    if "error" in result:
        error = result["error"]
        detail = str(error.get("message", "")) + " " + str(error.get("data", ""))
        normalized = detail.casefold()
        expired = any(x in normalized for x in (
            "session terminated", "session expired", "not authorized",
            "re-login", "session is invalid",
        ))
        if retry and expired:
            AUTH.invalidate()
            return api(url, AUTH.get(), method, params, retry=False)
        set_connection(False, "Zabbix API returned an error")
        raise RuntimeError("Zabbix API request failed")
    set_connection(True, "")
    return result.get("result", [])


def set_connection(connected, error):
    with CONNECTION_LOCK:
        CONNECTION["connected"] = connected
        CONNECTION["error"] = str(error)[:120]
        if connected:
            CONNECTION["last_success"] = int(time.time())


class BaseHandler(BaseHTTPRequestHandler):
    server_version = "StreamDockZabbix/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        origin = self.headers.get("Origin", "")
        allowed = (not origin or origin == "null" or
                   origin.startswith(("file://", "http://127.0.0.1:", "http://localhost:")))
        if self.client_address[0] not in (HOST, "::1") or not allowed:
            self.send_error(403)
            return
        if self.path.split("?")[0] != "/health":
            self.send_error(404)
            return
        with CONNECTION_LOCK:
            state = dict(CONNECTION)
        state.update({"running": True, "version": VERSION})
        payload = json.dumps(state, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", origin or "null")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def monitor():
    while True:
        try:
            cfg = config()
            url = cfg.get("zabbix_url", "")
            secret = AUTH.get()
            CATALOG.list_dashboards(api, url, secret)
            set_connection(True, "")
        except Exception as exc:
            set_connection(False, type(exc).__name__ + ": " + str(exc)[:100])
        time.sleep(45)


def setup_logger():
    logs = APP / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        logs / "bridge.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.setLevel(logging.INFO)
    LOG.addHandler(handler)


def selftest():
    marker = b"DPAPI smoke test"
    assert protect_bytes(protect_bytes(marker, True), False) == marker
    assert validate_url("https://zabbix.example.com") == "https://zabbix.example.com/api_jsonrpc.php"
    assert validate_url("https://zabbix.example.com/zabbix") == "https://zabbix.example.com/zabbix/api_jsonrpc.php"
    print("PASS: DPAPI, URL validation")


def main():
    parser = argparse.ArgumentParser(prog="streamdock-zabbix")
    parser.add_argument("command", nargs="?", choices=("serve", "set-login", "set-token", "selftest", "status", "version"),
                        default="serve")
    args = parser.parse_args()
    if args.command == "version":
        print("StreamDock Zabbix " + VERSION)
        return
    if args.command == "selftest":
        selftest()
        return
    if args.command == "set-login":
        url = validate_url(config().get("zabbix_url"))
        username = input("Zabbix username: ").strip()
        password = getpass.getpass("Zabbix password (hidden): ")
        if not username or not password:
            raise SystemExit("Username and password are required")
        AUTH._login(url, username, password)
        AUTH.store({"kind": "login", "username": username, "password": password})
        print("Zabbix login verified. Credentials stored with Windows DPAPI.")
        return
    if args.command == "set-token":
        token = getpass.getpass("Zabbix API token (hidden): ").strip()
        if not token:
            raise SystemExit("Token is required")
        api(config()["zabbix_url"], token, "dashboard.get", {"output": ["dashboardid", "name"]})
        AUTH.store({"kind": "token", "token": token})
        print("API token verified and protected with Windows DPAPI.")
        return
    if args.command == "status":
        with CONNECTION_LOCK:
            print(json.dumps(CONNECTION, ensure_ascii=False))
        return
    setup_logger()
    # Intentionally no HTTPS bypass: Windows certificate trust is required.
    from universal_http import handler_factory
    handler = handler_factory(BaseHandler, CATALOG, config, AUTH.get, api)
    Thread(target=monitor, name="zabbix-heartbeat", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print("StreamDock Zabbix bridge on http://%s:%d" % (HOST, PORT), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
