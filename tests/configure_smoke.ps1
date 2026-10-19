# Validates configuration without requesting a real Zabbix password.
[CmdletBinding()]
param([string]$Root)
$ErrorActionPreference = 'Stop'
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Temp = Join-Path $env:TEMP ('streamdock-config-qa-' + [guid]::NewGuid().ToString('N'))
$App = Join-Path $Temp 'app'
New-Item -ItemType Directory -Path $App -Force | Out-Null
try {
    Copy-Item (Join-Path $Root 'config.example.json') (Join-Path $App 'settings.json')
    # Safe stub: no network and no user input. It only records which CLI command is used.
    $stub = @'
import sys
from pathlib import Path
Path(__file__).with_suffix(".args").write_text(sys.argv[1], encoding="utf-8")
'@
    [IO.File]::WriteAllText((Join-Path $App 'bridge.py'), $stub)
    & (Join-Path $Root 'configure.ps1') -InstallPath $App -ZabbixUrl 'https://zabbix.example.com'
    $state = Get-Content (Join-Path $App 'settings.json') -Raw | ConvertFrom-Json
    if ($state.zabbix_url -ne 'https://zabbix.example.com') {throw 'Incorrect Zabbix URL stored'}
    if ((Get-Content (Join-Path $App 'bridge.args')) -ne 'set-login') {throw 'Username/password setup not invoked'}
    & (Join-Path $Root 'configure.ps1') -InstallPath $App -ZabbixUrl 'https://zabbix.example.com/monitoring' -UseToken
    if ((Get-Content (Join-Path $App 'bridge.args')) -ne 'set-token') {throw 'Token setup not invoked'}
    $state = Get-Content (Join-Path $App 'settings.json') -Raw | ConvertFrom-Json
    if ($state.zabbix_url -ne 'https://zabbix.example.com/monitoring') {throw 'URL path not saved'}
    if (Test-Path (Join-Path $App 'credentials.dpapi')) {throw 'Test created a real credential'}
    Write-Host 'PASS: configure URL, URL subpath, login mode, token mode, no credential leak' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $Temp) {Remove-Item -LiteralPath $Temp -Recurse -Force}
}
