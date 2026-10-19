"""Local read-only REST endpoints for universal AJAZZ/Zabbix plugin."""
from http import HTTPStatus
from urllib.parse import urlsplit, parse_qs
from time import time
import json

MAX_QUERY = 4096


def handler_factory(base, catalog, settings, get_token, api_call):
    class UniversalHandler(base):
        def api_response(self, obj, status=200, origin=""):
            body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Access-Control-Allow-Origin", origin if origin else "null")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.path.startswith("/api/"):
                return super().do_GET()
            origin = self.headers.get("Origin", "")
            allowed = (not origin or origin == "null" or
                       origin.startswith(("file://", "http://127.0.0.1:", "http://localhost:")))
            if self.client_address[0] not in ("127.0.0.1", "::1") or not allowed:
                self.send_error(403, "Forbidden")
                return
            if len(self.path) > MAX_QUERY:
                self.api_response({"error": "Слишком длинный запрос"}, 414, origin)
                return
            try:
                parsed = urlsplit(self.path)
                args = parse_qs(parsed.query, keep_blank_values=True)
                def arg(name):
                    items = args.get(name, [])
                    if len(items) != 1:
                        raise ValueError("Укажите " + name)
                    return items[0]
                conf = settings()
                url = conf["zabbix_url"]
                auth = get_token()
                if not auth:
                    raise RuntimeError("Авторизация Zabbix отсутствует")
                if parsed.path == "/api/catalog/dashboards":
                    payload = {"dashboards": catalog.list_dashboards(api_call, url, auth)}
                elif parsed.path == "/api/catalog/pages":
                    did = arg("dashboard_id")
                    payload = {
                        "dashboardId": did,
                        "pages": catalog.list_pages(did, api_call, url, auth),
                    }
                elif parsed.path == "/api/catalog/widgets":
                    did = arg("dashboard_id")
                    pid = arg("page_id")
                    payload = {
                        "dashboardId": did,
                        "pageId": pid,
                        "widgets": catalog.list_widgets(did, pid, api_call, url, auth),
                    }
                elif parsed.path == "/api/render":
                    keys = arg("keys")
                    tiles = catalog.render(keys, api_call, url, auth)
                    payload = {
                        "connected": True,
                        "updated_at": int(time()),
                        "tiles": tiles,
                    }
                else:
                    self.api_response({"error": "Ресурс не найден"}, 404, origin)
                    return
                self.api_response(payload, 200, origin)
            except ValueError as exc:
                self.api_response({"error": str(exc)[:150]}, 400, origin)
            except LookupError as exc:
                self.api_response({"error": str(exc)[:150]}, 404, origin)
            except (OSError, RuntimeError, KeyError) as exc:
                self.api_response({"error": str(exc)[:150]}, 503, origin)
            except Exception:
                self.api_response({"error": "Внутренняя ошибка моста Zabbix"}, 500, origin)

    return UniversalHandler
