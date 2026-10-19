# Contributing

Thank you for improving StreamDock Zabbix.

## Development

Requires Windows for DPAPI and installer tests; Python 3.9+ and Node.js for syntax checks.

Run:

    python -m unittest discover -s tests -v
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\install_smoke.ps1
    node --check .\plugin\com.streamdock.zabbix.sdPlugin\plugin.js
    node --check .\plugin\com.streamdock.zabbix.sdPlugin\inspector.js

Use synthetic Zabbix responses in tests. Do **not** include real server addresses, internal IPs, personal Windows paths, usernames, secrets, exported profiles, or company-specific dashboards in issues or pull requests.

Preserve read-only behavior. Avoid adding Zabbix API calls that modify the server. Keep runtime dependencies minimal.

If you change the manifest action UUID or the local bridge port, document the migration clearly, since this affects existing keys.

## Pull requests

Explain the user-facing change, security implications, and how it was tested. Prefer focused patches with reproducible tests.
