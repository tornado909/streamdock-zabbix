<#
.SYNOPSIS
Installs the read-only StreamDock Zabbix plugin and local Windows bridge.
.DESCRIPTION
Per-user, idempotent installer. It works from any current directory, including
an existing installation directory. It preserves settings and DPAPI credentials.
.EXAMPLE
.\install.ps1
.EXAMPLE
.\install.ps1 -InstallPath "$env:TEMP\ZabbixTest" -PluginPath "$env:TEMP\HotSpotTest" -NoStart -NoAutostart
#>
[CmdletBinding()]
param(
    [string]$InstallPath = (Join-Path $env:LOCALAPPDATA 'StreamDock-Zabbix'),
    [string]$PluginPath = (Join-Path $env:APPDATA 'HotSpot\StreamDock\plugins\com.streamdock.zabbix.sdPlugin'),
    [string]$StartupPath = (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\StreamDock-Zabbix.vbs'),
    [switch]$NoStart,
    [switch]$NoAutostart
)

$ErrorActionPreference = 'Stop'
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = [IO.Path]::GetFullPath($InstallPath)
$PluginDir = [IO.Path]::GetFullPath($PluginPath)
$PluginSource = Join-Path $SourceRoot 'plugin\com.streamdock.zabbix.sdPlugin'
$CodeSource = Join-Path $SourceRoot 'src'
$CodeNames = @('bridge.py', 'universal.py', 'universal_http.py')
$EntryPath = Join-Path $AppDir 'bridge.py'
$Port = 18398
$Startup = [IO.Path]::GetFullPath($StartupPath)

function Copy-IfDifferent {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Missing installation source: $Source"
    }
    $fullSource = [IO.Path]::GetFullPath($Source).TrimEnd('\')
    $fullDest = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if ([String]::Equals($fullSource, $fullDest, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "Already in place: $Destination"
        return
    }
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        if ([Convert]::ToBase64String(([System.Security.Cryptography.SHA256]::Create()).ComputeHash([IO.File]::ReadAllBytes($Source))) -eq
            [Convert]::ToBase64String(([System.Security.Cryptography.SHA256]::Create()).ComputeHash([IO.File]::ReadAllBytes($Destination)))) {
            return
        }
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Find-Python {
    $commands = @(
        @{Name='python'; Args=@('-c', 'import sys; print(sys.executable) if sys.version_info >= (3, 9) else sys.exit(1)')},
        @{Name='py'; Args=@('-3', '-c', 'import sys; print(sys.executable) if sys.version_info >= (3, 9) else sys.exit(1)')}
    )
    foreach ($entry in $commands) {
        try {
            $result = & $entry.Name @($entry.Args) 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            $path = ($result | Select-Object -First 1).Trim()
            if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) {
                $windowless = Join-Path (Split-Path $path -Parent) 'pythonw.exe'
                if (Test-Path -LiteralPath $windowless -PathType Leaf) {
                    return @{Python=$path; PythonW=$windowless}
                }
            }
        } catch { }
    }
    throw "Python 3.9+ with pythonw.exe is required. Install Python, then retry."
}

if (-not (Test-Path -LiteralPath $PluginSource -PathType Container)) {
    throw "Missing packaged plugin: $PluginSource. Run install.ps1 from an extracted release."
}
foreach ($name in $CodeNames) {
    $file = Join-Path $CodeSource $name
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        $file = Join-Path $SourceRoot $name
    }
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Missing backend module $name."
    }
}

$python = Find-Python
New-Item -ItemType Directory -Path $AppDir, $PluginDir -Force | Out-Null

# Stop only this bridge process, never unrelated Python instances.
if (-not $NoStart) {
    $oldProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in @('python.exe', 'pythonw.exe') -and
            $_.CommandLine -and
            $_.CommandLine.IndexOf($EntryPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
    foreach ($process in $oldProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    }
}

foreach ($name in $CodeNames) {
    $file = Join-Path $CodeSource $name
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        $file = Join-Path $SourceRoot $name
    }
    Copy-IfDifferent $file (Join-Path $AppDir $name)
}

$configTarget = Join-Path $AppDir 'settings.json'
if (-not (Test-Path -LiteralPath $configTarget -PathType Leaf)) {
    Copy-IfDifferent (Join-Path $SourceRoot 'config.example.json') $configTarget
}

Get-ChildItem -LiteralPath $PluginSource -File | ForEach-Object {
    Copy-IfDifferent $_.FullName (Join-Path $PluginDir $_.Name)
}

if (-not $NoAutostart) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $Startup) -Force | Out-Null
    # WSH/VBScript double-quote escaping: command has two quoted paths.
    $command = '""' + $python.PythonW + '"" ""' + $EntryPath + '"" serve'
    $vbs = 'CreateObject("WScript.Shell").Run "' + $command + '", 0, False'
    Set-Content -LiteralPath $Startup -Value $vbs -Encoding ASCII
}

if (-not $NoStart) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        throw "Port $Port is already in use. The package was copied but the bridge was not started."
    }
    Start-Process -FilePath $python.PythonW -ArgumentList ('"' + $EntryPath + '" serve') -WorkingDirectory $AppDir -WindowStyle Hidden
    $healthy = $false
    for ($attempt=0; $attempt -lt 15; $attempt++) {
        Start-Sleep -Milliseconds 400
        try {
            $status = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($status.running -eq $true -and $status.version -eq '1.0.0') {
                $healthy = $true
                break
            }
        } catch { }
    }
    if (-not $healthy) {
        throw "Bridge failed to start. Check $AppDir\logs\bridge.log and port $Port."
    }
}

Write-Host ""
Write-Host "StreamDock Zabbix 1.0.0 installed." -ForegroundColor Green
Write-Host "Backend: $AppDir"
Write-Host "HotSpot plugin: $PluginDir"
Write-Host "Configuration: $configTarget"
Write-Host "API: http://127.0.0.1:$Port"
Write-Host "Next: run configure.ps1 to specify Zabbix URL and set credentials."
Write-Host "Restart HotSpot to detect the plugin."
