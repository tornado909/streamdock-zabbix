<#
.SYNOPSIS
Set Zabbix server and credentials for the StreamDock Zabbix plugin.
.DESCRIPTION
Prompts for a password/token in the Python console (hidden input).
Credentials are encrypted using the Windows CurrentUser DPAPI.
#>
[CmdletBinding()]
param(
    [string]$InstallPath = (Join-Path $env:LOCALAPPDATA 'StreamDock-Zabbix'),
    [string]$ZabbixUrl,
    [switch]$UseToken
)

$ErrorActionPreference = 'Stop'
$AppDir = [IO.Path]::GetFullPath($InstallPath)
$Bridge = Join-Path $AppDir 'bridge.py'
$Config = Join-Path $AppDir 'settings.json'
if (-not (Test-Path -LiteralPath $Bridge -PathType Leaf)) {
    throw "Plugin bridge not installed. Run install.ps1 first."
}
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw "settings.json not installed. Run install.ps1 first."
}

if (-not $ZabbixUrl) {
    $ZabbixUrl = Read-Host 'Zabbix web URL (for example, https://zabbix.example.com)'
}
$ZabbixUrl = $ZabbixUrl.Trim().TrimEnd('/')
[Uri]$uri = $null
if (-not [Uri]::TryCreate($ZabbixUrl, [UriKind]::Absolute, [ref]$uri)) {
    throw 'Invalid Zabbix URL.'
}
if ($uri.Scheme -notin @('https', 'http') -or -not $uri.Host -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
    throw 'Invalid Zabbix URL. Do not embed username, password or query strings.'
}
if ($uri.Scheme -ne 'https') {
    Write-Warning 'Plain HTTP is not encrypted. HTTPS is strongly recommended.'
}
$data = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$data.zabbix_url = $ZabbixUrl
$json = $data | ConvertTo-Json -Depth 40
# Preserve existing configuration fields and overwrite only the URL.
[IO.File]::WriteAllText($Config, $json + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))

$python = $null
foreach ($exe in @('python', 'py')) {
    try {
        if ($exe -eq 'py') {
            $out = @(& py -3 -c 'import sys;print(sys.executable)' 2>$null)
        } else {
            $out = @(& python -c 'import sys;print(sys.executable)' 2>$null)
        }
        if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path -LiteralPath $out[0] -PathType Leaf)) {
            $python = $out[0]
            break
        }
    } catch { }
}
if (-not $python) { throw 'Python is not installed or was not found.' }

if ($UseToken) {
    & $python $Bridge set-token
} else {
    & $python $Bridge set-login
}
if ($LASTEXITCODE -ne 0) { throw 'Authentication failed; credentials were not replaced.' }

Write-Host "Configuration saved to $Config"
Write-Host 'The local bridge will pick up the new credentials automatically.'
Write-Host 'You can verify the bridge at http://127.0.0.1:18398/health'
