"""Bridge security, URL parsing and credential storage tests. Entirely offline."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import bridge


class BridgeTests(unittest.TestCase):
    def test_safe_endpoint_parsing(self):
        self.assertEqual(
            bridge.validate_url("https://zabbix.example.com"),
            "https://zabbix.example.com/api_jsonrpc.php")
        self.assertEqual(
            bridge.validate_url("https://zabbix.example.com/custom"),
            "https://zabbix.example.com/custom/api_jsonrpc.php")
        for url in ("", "zabbix.example.com", "file:///etc/passwd",
                    "https://user:password@host.local", "https://host.local/?token=123"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    bridge.validate_url(url)

    @unittest.skipUnless(os.name == "nt", "Windows CurrentUser DPAPI only")
    def test_dpapi_binary_roundtrip(self):
        secret = b"dummy smoke-test data"
        encrypted = bridge.protect_bytes(secret, True)
        self.assertNotEqual(secret, encrypted)
        self.assertEqual(bridge.protect_bytes(encrypted, False), secret)

    @unittest.skipUnless(os.name == "nt", "Windows CurrentUser DPAPI only")
    def test_credentials_store_and_login_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "credentials.dpapi"
            path = Path(directory) / "settings.json"
            path.write_text('{"zabbix_url":"https://zabbix.example.com"}', encoding="utf-8")
            auth = bridge.Auth()
            requests = []
            def fake_open(request, timeout):
                parsed = json.loads(request.data)
                self.assertEqual(parsed["method"], "user.login")
                self.assertEqual(parsed["params"]["username"], "demo_user")
                self.assertEqual(parsed["params"]["password"], "demo_pass")
                requests.append(parsed["method"])
                return io.BytesIO(b'{"jsonrpc":"2.0","result":"dummy_session","id":1}')
            with patch.object(bridge, "SECRETS", location), patch.object(bridge, "SETTINGS", path):
                with patch.object(bridge.urllib.request, "urlopen", fake_open):
                    auth.store({"kind": "login", "username": "demo_user", "password": "demo_pass"})
                    self.assertTrue(location.is_file())
                    self.assertNotIn(b"demo_pass", location.read_bytes())
                    self.assertEqual(auth.get(), "dummy_session")
                    self.assertEqual(auth.get(), "dummy_session")
                    self.assertEqual(requests, ["user.login"])
                    auth.invalidate()
                    self.assertEqual(auth.get(), "dummy_session")
                    self.assertEqual(requests, ["user.login", "user.login"])

    def test_api_bearer_header_and_error_is_sanitized(self):
        request_seen = []
        def ok_request(request, timeout):
            self.assertEqual(request.get_header("Authorization"), "Bearer demo-token")
            request_seen.append(request)
            return io.BytesIO(b'{"jsonrpc":"2.0","result":[],"id":1}')
        with patch.object(bridge.urllib.request, "urlopen", ok_request):
            self.assertEqual(
                bridge.api("https://zabbix.example.com", "demo-token", "dashboard.get", {"output":["dashboardid"]}), [])
        self.assertEqual(len(request_seen), 1)
        def bad_request(request, timeout):
            return io.BytesIO(b'{"jsonrpc":"2.0","error":{"message":"Invalid params.","data":"secret-text"},"id":1}')
        with patch.object(bridge.urllib.request, "urlopen", bad_request):
            with self.assertRaisesRegex(RuntimeError, "Zabbix API request failed") as exc:
                bridge.api("https://zabbix.example.com", "demo-token", "dashboard.get", {})
            self.assertNotIn("secret-text", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
