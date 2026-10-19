# Safe, temporary installation tests. Does not touch the user's HotSpot profile.
[CmdletBinding()]
param([string]$Root)
$ErrorActionPreference='Stop'
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$TempBase=Join-Path $env:TEMP ('streamdock-zabbix-qa-' + [guid]::NewGuid().ToString('N'))
$App=Join-Path $TempBase 'app'
$Plugin=Join-Path $TempBase 'plugins\com.streamdock.zabbix.sdPlugin'
New-Item -ItemType Directory -Path $TempBase -Force | Out-Null
try {
    # First install, then repeat with a deliberately customized config.
    & (Join-Path $Root 'install.ps1') -InstallPath $App -PluginPath $Plugin -NoStart -NoAutostart
    if (-not (Test-Path (Join-Path $Plugin 'manifest.json'))) {throw 'Plugin not installed'}
    $Cfg=Join-Path $App 'settings.json'
    $Settings=Get-Content $Cfg -Raw | ConvertFrom-Json
    $Settings.zabbix_url='https://custom.example.com'
    $Settings | ConvertTo-Json | Set-Content -LiteralPath $Cfg -Encoding UTF8
    $Sha=[Convert]::ToBase64String(([System.Security.Cryptography.SHA256]::Create()).ComputeHash([IO.File]::ReadAllBytes($Cfg)))
    [IO.File]::WriteAllBytes((Join-Path $App 'credentials.dpapi'),[Text.Encoding]::ASCII.GetBytes('dummy-credentials-only'))
    & (Join-Path $Root 'install.ps1') -InstallPath $App -PluginPath $Plugin -NoStart -NoAutostart
    if ([Convert]::ToBase64String(([System.Security.Cryptography.SHA256]::Create()).ComputeHash([IO.File]::ReadAllBytes($Cfg))) -ne $Sha) {throw 'Reinstall overwrote user configuration'}
    if (([IO.File]::ReadAllText((Join-Path $App 'credentials.dpapi'))) -ne 'dummy-credentials-only') {
        throw 'Reinstall modified DPAPI credentials'
    }

    # Verify autostart quotation safely in a temporary folder.
    $StartupFile=Join-Path $TempBase 'fake-startup\\StreamDock-Zabbix.vbs'
    & (Join-Path $Root 'install.ps1') -InstallPath $App -PluginPath $Plugin -NoStart -StartupPath $StartupFile
    if (-not (Test-Path -LiteralPath $StartupFile)) {throw 'Autostart shortcut missing'}
    $Vbs=Get-Content -LiteralPath $StartupFile -Raw
    if ($Vbs -notmatch 'pythonw.exe' -or $Vbs -notmatch 'bridge.py') {throw 'Autostart command malformed'}

    # Source and install directory the same: old installer would copy a file onto itself.
    $Same=Join-Path $TempBase 'inplace'
    Copy-Item -LiteralPath $Root -Destination $Same -Recurse
    $SamePlugin=Join-Path $Same 'plugin\com.streamdock.zabbix.sdPlugin'
    & (Join-Path $Same 'install.ps1') -InstallPath $Same -PluginPath $SamePlugin -NoStart -NoAutostart
    & (Join-Path $Same 'install.ps1') -InstallPath $Same -PluginPath $SamePlugin -NoStart -NoAutostart
    if (-not (Test-Path (Join-Path $Same 'bridge.py'))) {throw 'In-place installation failed'}
    if (-not (Test-Path (Join-Path $Same 'settings.json'))) {throw 'In-place configuration missing'}

    # Uninstall must leave configuration and DPAPI data intact by default.
    & (Join-Path $Root 'uninstall.ps1') -InstallPath $App -PluginPath $Plugin -StartupPath $StartupFile
    if (Test-Path -LiteralPath $StartupFile) {throw 'Uninstall left startup shortcut'}
    if (Test-Path (Join-Path $Plugin 'manifest.json')) {throw 'Uninstall left plugin'}
    if (-not (Test-Path (Join-Path $App 'credentials.dpapi'))) {throw 'Uninstall destroyed credentials'}
    if (-not (Test-Path $Cfg)) {throw 'Uninstall destroyed configuration'}
    Write-Host 'PASS: new install, repeat install, in-place installation, self-copy avoidance, safe uninstall' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $TempBase) {
        Remove-Item -LiteralPath $TempBase -Recurse -Force
    }
}
