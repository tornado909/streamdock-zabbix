# Security policy

## Reporting vulnerabilities

Please do not publish credentials, private monitoring screenshots, API responses, or exploit details in public issues.

When this project is hosted on GitHub, use **Report a vulnerability** under the repository's **Security** tab (private vulnerability reporting). If that feature is unavailable, open a minimal issue without sensitive details to request a secure reporting channel.

## Local trust boundary

- The helper HTTP API only binds to 127.0.0.1, port 18398.
- Zabbix access is read-only, with the minimum privileges needed to list dashboards and read items.
- The bridge runs as the currently signed-in Windows user, not as Administrator.
- Passwords and API tokens use Windows CurrentUser DPAPI; never copy credentials.dpapi into a repository or release.
- HTTPS certificate validation is not disabled.
- Because the helper API serves data over localhost, do not expose or forward port 18398 or use this app on untrusted shared desktops.
- The plugin stores only numeric IDs and optional display labels inside HotSpot profiles.

## Supported versions

Version 1.0.x receives best-effort security fixes. Do not rely on the plugin as a security incident paging or safety-critical alarm system.

## Dependency policy

Python 3.9+ standard library only. Front-end files use the native HotSpot plugin interface; there is no online CDN.
