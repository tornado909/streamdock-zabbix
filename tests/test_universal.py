"""Offline integration tests. No network, accounts, hosts, or credentials required."""
import json
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from universal import Catalog, parse_widget, select_keys, state_for
from universal_http import handler_factory
from bridge import BaseHandler


def make_widget(wid, itemid, label, x, thresholds, metric=True):
    fields = [
        {"name": "description", "value": label},
        {"name": "show.0", "value": 1},
        {"name": "decimal_places", "value": 0},
        {"name": "units_show", "value": 0},
    ]
    if itemid:
        fields.append({"name": "itemid.0", "value": str(itemid)})
    if metric:
        fields.append({"name": "show.1", "value": 2})
    for index, (value, color) in enumerate(thresholds):
        fields.extend([
            {"name": f"thresholds.{index}.threshold", "value": value},
            {"name": f"thresholds.{index}.color", "value": color},
        ])
    return {"widgetid": str(wid), "type": "item", "name": label, "x": str(x), "y": "1", "fields": fields}


class MockZabbix:
    def __init__(self):
        self.stats = Counter()

    def __call__(self, url, secret, method, params):
        self.stats[method] += 1
        if method == "dashboard.get":
            if "dashboardids" not in params:
                return [{"dashboardid": "1", "name": "Operations"}, {"dashboardid": "2", "name": "Lab"}]
            which = str(params["dashboardids"][0])
            if which == "1":
                return [{"dashboardid": "1", "name": "Operations", "pages": [
                    {"dashboard_pageid": "11", "name": "Servers", "widgets": [
                        make_widget(110, 101, "CPU A", 0, [(0, "4CAF50"), (70, "FFD54F"), (85, "FF0000")]),
                        make_widget(111, 102, "Health", 3, [(1, "FF0000"), (3, "4CAF50"), (4, "FF0000")], metric=False),
                        make_widget(112, None, "No source", 6, [(0, "4CAF50")]),
                        {"widgetid": "113", "type": "svggraph", "fields": []},
                    ]},
                    {"dashboard_pageid": "12", "name": "Storage", "widgets": [
                        make_widget(114, 101, "CPU again", 0, [(0, "4CAF50")])
                    ]},
                ]}]
            if which == "2":
                return [{"dashboardid": "2", "name": "Lab", "pages": [
                    {"dashboard_pageid": "21", "name": "UPS", "widgets": [
                        make_widget(211, 103, "Battery", 0, [(0, "4CAF50"), (25, "FF0000")]),
                    ]}
                ]}]
            return []
        if method == "item.get":
            return [
                {"itemid": str(i), "lastvalue": {101: "76", 102: "4", 103: "16"}[int(i)],
                 "lastclock": str(int(time.time())), "state": "0", "status": "0",
                 "name": {101: "CPU", 102: "Health", 103: "UPS"}[int(i)],
                 "units": "°C", "hosts": [{"host": "demo", "name": "Demo Server"}]}
                for i in params["itemids"]
            ]
        raise AssertionError(f"Unexpected Zabbix method: {method}")


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.mock = MockZabbix()
        self.catalog = Catalog()

    def test_dashboards_pages_and_widget_choices(self):
        dashboards = self.catalog.list_dashboards(self.mock, "https://demo.example", "mock")
        self.assertEqual([d["name"] for d in dashboards], ["Lab", "Operations"])
        pages = self.catalog.list_pages("1", self.mock, "https://demo.example", "mock")
        self.assertEqual([p["widgetsCount"] for p in pages], [3, 1])
        widgets = self.catalog.list_widgets("1", "11", self.mock, "https://demo.example", "mock")
        self.assertEqual(len(widgets), 3)
        self.assertEqual(widgets[0]["host"], "Demo Server")
        self.assertFalse(widgets[2]["resolved"])
        self.assertEqual(widgets[2]["itemId"], "")

    def test_render_multiple_dashboard_and_item_colors(self):
        keys = "1:11:110,1:11:111,2:21:211"
        result = self.catalog.render(keys, self.mock, "https://demo.example", "mock")
        self.assertEqual(result["1:11:110"]["display"], "76")
        self.assertEqual(result["1:11:110"]["color"], "#FFD54F")
        self.assertEqual(result["1:11:111"]["display"], "")
        self.assertEqual(result["1:11:111"]["state"], "problem")
        self.assertEqual(result["2:21:211"]["color"], "#4CAF50")
        self.assertIn("dashboardid=2", result["2:21:211"]["url"])
        self.assertEqual(self.catalog.render("1:11:112", self.mock, "https://demo.example", "mock")["1:11:112"]["state"], "unknown")

    def test_cache_and_missing_widgets(self):
        self.catalog.render("1:11:110,1:11:111", self.mock, "https://demo.example", "mock")
        dashboard_calls = self.mock.stats["dashboard.get"]
        item_calls = self.mock.stats["item.get"]
        self.catalog.render("1:11:110,1:11:111", self.mock, "https://demo.example", "mock")
        self.assertEqual(self.mock.stats["dashboard.get"], dashboard_calls)
        self.assertEqual(self.mock.stats["item.get"], item_calls)
        empty = self.catalog.render("1:11:999", self.mock, "https://demo.example", "mock")
        self.assertEqual(empty["1:11:999"]["state"], "unknown")

    def test_invalid_input(self):
        for sample in ("", "abc", "1:1:0", "1:2:3;DROP", "1:1:1,evil", "0:1:1"):
            with self.subTest(sample=sample):
                with self.assertRaises(ValueError):
                    select_keys(sample)

    def test_stale_and_unsupported_items(self):
        widget = parse_widget(make_widget(500, 999, "test", 0, [(0, "4CAF50")]))
        now = int(time.time())
        old = {"lastvalue": "20", "lastclock": now - 10000}
        self.assertEqual(state_for(old, widget, now=now)["state"], "unknown")
        broken = {"lastvalue": "20", "lastclock": now, "state": "1"}
        self.assertEqual(state_for(broken, widget, now=now)["state"], "unknown")

    def test_local_rest_endpoints_and_no_external_origin(self):
        bridge = handler_factory(BaseHandler, self.catalog,
                                 lambda: {"zabbix_url": "https://demo.example"},
                                 lambda: "mock", self.mock)
        server = ThreadingHTTPServer(("127.0.0.1", 0), bridge)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(server.server_address[1])
        try:
            with urlopen(base + "/api/catalog/dashboards") as response:
                self.assertEqual(len(json.load(response)["dashboards"]), 2)
            with urlopen(base + "/api/catalog/pages?dashboard_id=1") as response:
                self.assertEqual(len(json.load(response)["pages"]), 2)
            with urlopen(base + "/api/catalog/widgets?dashboard_id=1&page_id=11") as response:
                self.assertEqual(len(json.load(response)["widgets"]), 3)
            with urlopen(base + "/api/render?keys=" + quote("1:11:110")) as response:
                self.assertEqual(json.load(response)["tiles"]["1:11:110"]["state"], "warning")
            with self.assertRaises(HTTPError) as context:
                urlopen(base + "/api/render?keys=bad")
            self.assertEqual(context.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
