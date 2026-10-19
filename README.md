# StreamDock Zabbix

A read-only Zabbix dashboard widget plugin for StreamDock / HotSpot LCD keypad devices on Windows.

Select **a dashboard, a dashboard page, and an Item value widget** for each key. The plugin displays the widget's latest value, caption and threshold colors via the Zabbix JSON-RPC API. No hardcoded Zabbix hosts or item IDs are necessary.

[Русская документация](README.ru.md)

## Features

- Independent settings per key: dashboard dropdown, manual dashboard ID, page dropdown, item-value widget dropdown.
- Different keys may monitor different dashboards and pages.
- Values or statuses with the colors defined by the selected Zabbix widget.
- Values refreshed every **5 seconds**; dashboard definitions cached for **60 seconds**.
- Pressing a key opens its source dashboard in the browser.
- Unreadable or unbound widgets are shown but disabled, never guessed.
- Missing, disabled or stale item values appear in neutral gray.
- One loopback-only Python bridge shares the connection among keys.
- Credentials encrypted with Windows CurrentUser DPAPI, never embedded in the plugin or exported profile.
- Repeatable per-user installation, automatic startup and safe uninstallation.

This is independent community software, not an official Zabbix or device-vendor project.

## Requirements

- Windows 10 or Windows 11.
- StreamDock / HotSpot with support for custom .sdPlugin actions (SDK v1, HotSpot 2.9+).
- Python **3.9+**, including pythonw.exe, available from python or py -3.
- A Zabbix API endpoint reachable over HTTPS (verified with **Zabbix 7.0**).
- A Zabbix user or token with read access to dashboards and items: dashboard.get and item.get.
- No third-party Python dependencies.

## Quick install

Download the source or release ZIP, **extract it**, and run from PowerShell in the extracted directory:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\configure.ps1

The installer copies bridge modules into:

    %LOCALAPPDATA%\StreamDock-Zabbix

It installs the plugin at:

    %APPDATA%\HotSpot\StreamDock\plugins\com.streamdock.zabbix.sdPlugin

The installer creates settings.json only when absent, sets up a per-user autostart entry and starts the local bridge.

Configuration asks for the Zabbix URL (including an optional /zabbix path), username and password. The password prompt is hidden. For an API token instead, run:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\configure.ps1 -UseToken

**Restart HotSpot** after installation.

### Select a widget

1. Add the **Monitoring → Zabbix: Item widget** action to a free LCD key.
2. Select a dashboard, or type a numeric Dashboard ID and click **Open**.
3. Select a dashboard page.
4. Select a widget of type **Item value**. The list shows widget name, monitored host, item name and widget ID.
5. Enter an optional custom label.
6. Click **Save selection**.

Each key stores its own dashboardId, pageId and widgetId in the HotSpot profile. A global list of item IDs is not required.

### Check connection

The bridge listens on the local machine only:

    http://127.0.0.1:18398/health

Check it from PowerShell:

    Invoke-RestMethod http://127.0.0.1:18398/health

A running bridge returns **running: true**. **connected: true** confirms that the Zabbix API is reachable and authentication succeeded. Logs are saved under the installation directory in logs/.

### Updating / repeat installation

Re-run install.ps1. Existing settings.json and credentials.dpapi are not overwritten. Source/destination file equality is checked to avoid the common PowerShell self-copy error.

Custom installation location:

    .\install.ps1 -InstallPath "D:\Apps\StreamDock-Zabbix"

To copy into isolated folders without running a process or installing autostart:

    .\install.ps1 -InstallPath "$env:TEMP\ZabbixTest" -PluginPath "$env:TEMP\HotSpotTest" -NoStart -NoAutostart

### Uninstall

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1

By default, this removes only plugin binaries and autostart, **preserving** your user settings and encrypted credentials. To remove your settings as well:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1 -PurgeUserData

Other applications, HotSpot profiles, and unrelated plugins are not modified.

## Repository

    plugin/com.streamdock.zabbix.sdPlugin/
      manifest.json       Plugin metadata and action
      plugin.js           Button image rendering and polling
      inspector.html/js   Dashboard/page/widget property inspector
      icon.png            Generic plugin icon
    src/
      bridge.py           Local bridge, Windows DPAPI and Zabbix API
      universal.py        Dashboard catalog, colors and values
      universal_http.py   Read-only local HTTP API
    tests/                Python and Windows installer tests
    config.example.json   Empty generic configuration
    install.ps1
    configure.ps1
    uninstall.ps1

API routes:

| Route | Purpose |
| --- | --- |
| /health | Local process and Zabbix connection status |
| /api/catalog/dashboards | Accessible dashboards |
| /api/catalog/pages?dashboard_id=... | Pages of a dashboard |
| /api/catalog/widgets?dashboard_id=...&page_id=... | Item value widgets |
| /api/render?keys=dashboard:page:widget | Latest values, labels and colors |

The Zabbix access is **read-only**: user.login, dashboard.get and item.get are the only called Zabbix methods.

If a widget uses a dynamic host reference and its API definition does not contain itemid.0, it is listed as **unbound** and cannot be selected. It would be incorrect to invent the item binding.

## Tests

    python -m unittest discover -s tests -v
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\install_smoke.ps1
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\configure_smoke.ps1
    node --check .\plugin\com.streamdock.zabbix.sdPlugin\plugin.js
    node --check .\plugin\com.streamdock.zabbix.sdPlugin\inspector.js

GitHub Actions runs automated tests for commits and pull requests.

## Privacy and security

- The packaged configuration contains **no** real Zabbix address, internal host, username, password, token, Windows profile or exported dashboard data.
- Credentials are stored as an encrypted Windows DPAPI file under the current user and are not portable to another Windows account.
- The bridge binds to 127.0.0.1 only. Never forward or publish TCP port 18398.
- HTTPS certificate validation is enabled. Do not bypass TLS verification.
- Never commit settings.json, credentials.dpapi, logs, exported HotSpot profiles or Zabbix diagnostic output.

See [SECURITY.md](SECURITY.md).

## Building a release

Stage only the files intended for public distribution in Git, then run:

    git add -A
    python scripts/build_release.py

The script packages **only files tracked by Git** into dist/ and creates a SHA-256 checksum. It rejects local settings, DPAPI files, HotSpot profiles and other sensitive file types. Review all changes and check the archive before publishing.

## License

MIT. See [LICENSE](LICENSE).
