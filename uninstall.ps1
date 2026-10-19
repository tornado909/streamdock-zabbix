<#
.SYNOPSIS
Remove the StreamDock Zabbix plugin and bridge.
.DESCRIPTION
By default credentials and settings are preserved. Use -PurgeUserData to remove them.
Never removes user HotSpot profiles or unrelated plugins.
#>
[CmdletBinding()]
param(
    [string]$InstallPath = (Join-Path $env:LOCALAPPDATA 'StreamDock-Zabbix'),
    [string]$PluginPath = (Join-Path $env:APPDATA 'HotSpot\StreamDock\plugins\com.streamdock.zabbix.sdPlugin'),
    [string]$StartupPath = (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\StreamDock-Zabbix.vbs'),
    [switch]$PurgeUserData
)
$ErrorActionPreference = 'Stop'
$AppDir = [IO.Path]::GetFullPath($InstallPath)
$PluginDir = [IO.Path]::GetFullPath($PluginPath)
$Bridge = Join-Path $AppDir 'bridge.py'
$Startup = [IO.Path]::GetFullPath($StartupPath)

# Match on the complete installation path to avoid stopping unrelated Python.
$procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -in @('python.exe', 'pythonw.exe') -and
        $_.CommandLine -and
        $_.CommandLine.IndexOf($Bridge, [StringComparison]::OrdinalIgnoreCase) -ge 0
    })
foreach ($process in $procs) {
    Stop-Process -Id $process.ProcessId -Force
}
if (Test-Path -LiteralPath $Startup) {
    Remove-Item -LiteralPath $Startup -Force
}

if (Test-Path -LiteralPath $PluginDir -PathType Container) {
    $manifestPath = Join-Path $PluginDir 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw 'Plugin folder has no manifest; refusing to delete it.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if (@($manifest.Actions | Where-Object { $_.UUID -eq 'com.streamdock.zabbix.widget' }).Count -ne 1) {
        throw 'Plugin directory does not match StreamDock Zabbix; refusing to delete it.'
    }
    Remove-Item -LiteralPath $PluginDir -Recurse -Force
}
if (Test-Path -LiteralPath $AppDir -PathType Container) {
    foreach ($name in @('bridge.py', 'universal.py', 'universal_http.py')) {
        $file = Join-Path $AppDir $name
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            Remove-Item -LiteralPath $file -Force
        }
    }
    if ($PurgeUserData) {
        $existing = @('settings.json', 'credentials.dpapi', 'logs')
        foreach ($name in $existing) {
            $path = Join-Path $AppDir $name
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force -Recurse
            }
        }
    }
}
Write-Host 'StreamDock Zabbix plugin and bridge removed.' -ForegroundColor Green
if (-not $PurgeUserData) {
    Write-Host "Settings and DPAPI credentials preserved at: $AppDir"
}
