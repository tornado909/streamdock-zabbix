"""Read-only universal Zabbix dashboard/item widget discovery and live rendering.

Public API uses only numeric dashboard/page/widget IDs, never accepts credentials or
a remote URL. Zabbix authentication stays in the bridge's Windows DPAPI store.
"""
from __future__ import annotations

from collections import defaultdict
from threading import RLock
from time import monotonic, time
from typing import Callable
import math
import re

HEALTH_OK = {"4CAF50", "43A047", "66BB6A"}
HEALTH_PROBLEM = {"FF0000", "FF465C", "F44336", "E53935"}
HEALTH_WARNING = {"FFFF00", "FFD54F", "FFC107", "FF9800"}
UNKNOWN_COLOR = "#545E68"
ID = re.compile(r"^[1-9][0-9]{0,19}$")
SELECTION = re.compile(r"^([1-9][0-9]{0,19}):([1-9][0-9]{0,19}):([1-9][0-9]{0,19})$")
THRESHOLD = re.compile(r"^thresholds\.([0-9]+)\.threshold$")
COLOR = re.compile(r"^[0-9A-Fa-f]{6}$")


def identifier(raw):
    candidate = str(raw).strip()
    if not ID.fullmatch(candidate):
        raise ValueError("Укажите числовой ID Zabbix")
    return candidate


def select_keys(raw):
    if not raw or len(raw) > 2500:
        raise ValueError("Некорректный список виджетов")
    keys = []
    for candidate in raw.split(","):
        candidate = candidate.strip()
        if not SELECTION.fullmatch(candidate):
            raise ValueError("Некорректный ID виджета")
        if candidate not in keys:
            keys.append(candidate)
        if len(keys) > 60:
            raise ValueError("Слишком много виджетов")
    return keys


def normalize_label(raw):
    label = re.sub(r"[\r\n]+", "\n", str(raw or "")).strip()
    label = re.sub(r"\n{2,}", "\n", label)
    if "\ufffd" in label or "????" in label:
        return ""
    return label[:100]


def parse_widget(widget):
    if widget.get("type") != "item":
        return None
    fields = {str(f["name"]): f.get("value") for f in widget.get("fields", []) if "name" in f}
    itemid = str(fields.get("itemid.0") or "")
    if not ID.fullmatch(itemid):
        itemid = ""
    boundaries = []
    for name, threshold in fields.items():
        match = THRESHOLD.fullmatch(name)
        if not match:
            continue
        suffix = match.group(1)
        color = str(fields.get("thresholds." + suffix + ".color") or "").strip().lstrip("#")
        if not COLOR.fullmatch(color):
            continue
        try:
            at = float(threshold)
        except (ValueError, TypeError):
            continue
        if math.isfinite(at):
            boundaries.append({"at": at, "color": "#" + color.upper()})
    boundaries.sort(key=lambda step: step["at"])
    name = normalize_label(fields.get("description")) or normalize_label(widget.get("name"))
    decimals = fields.get("decimal_places")
    if str(decimals).isdigit():
        decimals = min(3, max(0, int(decimals)))
    else:
        decimals = 0
    kind = "metric" if str(fields.get("show.1", "")) == "2" else "status_item"
    return {
        "widgetId": str(widget["widgetid"]), "itemId": itemid,
        "name": name, "type": "item", "kind": kind, "resolved": bool(itemid),
        "thresholds": boundaries, "decimals": decimals,
        "hideUnits": str(fields.get("units_show", "1")) == "0",
        "x": int(widget.get("x", 0)), "y": int(widget.get("y", 0)),
    }


def state_for(item, widget, now=None):
    now = int(time() if now is None else now)
    fallback_name = widget.get("name") or item.get("name", "") if item else widget.get("name", "")
    result = {
        "state": "unknown", "color": UNKNOWN_COLOR, "display": "?",
        "kind": widget.get("kind", "metric"), "label": fallback_name,
        "detail": "НЕТ ДАННЫХ", "widgetId": widget["widgetId"], "itemId": widget["itemId"],
    }
    if not item:
        result["detail"] = "ДАТЧИК НЕ НАЙДЕН"
        return result
    if str(item.get("state", "0")) == "1" or str(item.get("status", "0")) == "1":
        result["detail"] = "ДАТЧИК НЕ ПОДДЕРЖИВАЕТСЯ"
        return result
    lastclock = int(item.get("lastclock", 0) or 0)
    if not lastclock or now - lastclock > 900:
        result["detail"] = "НЕТ СВЕЖИХ ДАННЫХ"
        return result
    raw = str(item.get("lastvalue", ""))
    number = None
    try:
        val = float(raw)
        if math.isfinite(val):
            number = val
    except (TypeError, ValueError):
        pass
    steps = widget.get("thresholds") or []
    if number is not None and steps:
        candidates = [step for step in steps if number >= step["at"]]
        if candidates:
            result["color"] = candidates[-1]["color"]
            hex_color = result["color"].lstrip("#").upper()
            if hex_color in HEALTH_OK:
                result["state"] = "ok"
            elif hex_color in HEALTH_PROBLEM:
                result["state"] = "problem"
            elif hex_color in HEALTH_WARNING:
                result["state"] = "warning"
            else:
                result["state"] = "warning"
    if result["kind"] == "status_item":
        result["display"] = ""
        result["detail"] = "OK" if result["state"] == "ok" else "ПРОБЛЕМА" if result["state"] == "problem" else "ПРЕДУПРЕЖДЕНИЕ" if result["state"] == "warning" else "БЕЗ ПОРОГА"
    else:
        result["display"] = f"{number:.{widget['decimals']}f}" if number is not None else (raw[:14] or "?")
        result["detail"] = "" if widget.get("hideUnits") else str(item.get("units") or "").replace("�", "°")[:8]
    return result


class Catalog:
    def __init__(self):
        self.lock = RLock()
        self.dashboards = None
        self.dashboards_at = 0.0
        self.pages_cache = {}
        self.items_cache = {}

    def list_dashboards(self, api, url, secret):
        with self.lock:
            if self.dashboards is not None and monotonic() - self.dashboards_at < 60:
                return list(self.dashboards)
            rows = api(url, secret, "dashboard.get", {"output": ["dashboardid", "name"], "limit": 1000})
            result = sorted(
                [{"dashboardId": str(d["dashboardid"]), "name": str(d.get("name") or "Без названия")}
                 for d in rows if ID.fullmatch(str(d.get("dashboardid", "")))],
                key=lambda d: d["name"].casefold()
            )
            self.dashboards = result
            self.dashboards_at = monotonic()
            return list(result)

    def dashboard(self, dashboard_id, api, url, secret):
        dashboard_id = identifier(dashboard_id)
        with self.lock:
            cache = self.pages_cache.get(dashboard_id)
            if cache and monotonic() - cache[0] < 60:
                return cache[1]
            response = api(url, secret, "dashboard.get", {
                "dashboardids": [dashboard_id],
                "output": ["dashboardid", "name"],
                "selectPages": "extend",
            })
            if not response:
                raise LookupError("Дашборд недоступен или не существует")
            result = response[0]
            pages = {}
            for page in result.get("pages", []):
                pid = str(page.get("dashboard_pageid", ""))
                if not ID.fullmatch(pid):
                    continue
                widgets = {}
                for raw in page.get("widgets", []):
                    parsed = parse_widget(raw)
                    if parsed:
                        widgets[parsed["widgetId"]] = parsed
                pages[pid] = {"pageId": pid, "name": str(page.get("name") or "Без названия"),
                              "widgets": widgets}
            record = {"dashboardId": dashboard_id, "name": str(result.get("name", "")), "pages": pages}
            self.pages_cache[dashboard_id] = (monotonic(), record)
            return record

    def list_pages(self, dashboard_id, api, url, secret):
        record = self.dashboard(dashboard_id, api, url, secret)
        return [{"pageId": p["pageId"], "name": p["name"], "widgetsCount": len(p["widgets"])}
                for p in record["pages"].values()]

    def batch_items(self, itemids, api, url, secret):
        itemids = {identifier(i) for i in itemids if str(i).strip()}
        if not itemids:
            return {}
        with self.lock:
            now = monotonic()
            stale = [i for i in itemids if i not in self.items_cache or now - self.items_cache[i][0] > 3]
            if stale:
                for start in range(0, len(stale), 200):
                    ids = stale[start:start + 200]
                    result = api(url, secret, "item.get", {
                        "itemids": ids, "output": ["itemid", "name", "lastvalue", "lastclock", "units", "state", "status"],
                        "selectHosts": ["host", "name"],
                    })
                    by_id = {str(v["itemid"]): v for v in result}
                    for ident in ids:
                        self.items_cache[ident] = (monotonic(), by_id.get(ident))
            return {i: self.items_cache[i][1] for i in itemids}

    def list_widgets(self, dashboard_id, page_id, api, url, secret):
        dashboard = self.dashboard(dashboard_id, api, url, secret)
        page = dashboard["pages"].get(identifier(page_id))
        if page is None:
            raise LookupError("Страница дашборда недоступна")
        widgets = page["widgets"]
        items = self.batch_items([w["itemId"] for w in widgets.values()], api, url, secret)
        choices = []
        for widget in widgets.values():
            entry = items.get(widget["itemId"]) or {}
            hosts = entry.get("hosts") or []
            host = ", ".join(str(h.get("name") or h.get("host") or "") for h in hosts[:2])
            label = widget["name"] or str(entry.get("name") or "Без названия")
            choices.append({
                "widgetId": widget["widgetId"],
                "itemId": widget["itemId"],
                "name": label, "host": host, "resolved": widget["resolved"],
                "itemName": str(entry.get("name") or ""), "kind": widget["kind"],
                "x": widget["x"], "y": widget["y"],
            })
        return sorted(choices, key=lambda w: (w["y"], w["x"]))

    def render(self, keys, api, url, secret):
        keys = select_keys(keys) if isinstance(keys, str) else list(keys)
        dashboards = {}
        widgets = {}
        for key in keys:
            match = SELECTION.fullmatch(key)
            if not match:
                raise ValueError("Недопустимый ID виджета")
            did, pid, wid = match.groups()
            if did not in dashboards:
                dashboards[did] = self.dashboard(did, api, url, secret)
            page = dashboards[did]["pages"].get(pid)
            widget = page and page["widgets"].get(wid)
            widgets[key] = (did, pid, widget)
        items = self.batch_items([w["itemId"] for _,_,w in widgets.values() if w and w["itemId"]], api, url, secret)
        result = {}
        for key, (did, pid, widget) in widgets.items():
            if widget is None:
                result[key] = {"state":"unknown","color":UNKNOWN_COLOR,"kind":"metric","display":"?",
                               "label":"Zabbix","detail":"ВИДЖЕТ НЕДОСТУПЕН","url":url}
                continue
            status = state_for(items.get(widget["itemId"]), widget)
            if not widget["resolved"]:
                status["detail"] = "НЕТ ПРИВЯЗКИ ЭЛЕМЕНТА"
            status["url"] = url.rstrip("/") + "/zabbix.php?action=dashboard.view&dashboardid=" + did
            status["dashboardId"] = did
            status["pageId"] = pid
            result[key] = status
        return result
