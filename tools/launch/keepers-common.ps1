# DF AI Overseer: what the keepers' window (start-keepers.ps1) and the
# watchdog (keeper-watchdog.ps1) share, so the two never drift (F5a, 27 Nov 2026).
# Dot-sourced by both: . (Join-Path $PSScriptRoot 'keepers-common.ps1')
# Lives beside them in Documents (each fort's folder is Documents\<Dir>).
#
# Markers, each JSON {"by": ..., "why": ..., "at": ISO time}:
#   <fort>\logs\keeper-stop               asks that fort's keeper to stop (it logs by/why)
#   <fort>\logs\keeper-owner-stop.json    the owner stopped it: the watchdog won't start it
#   DF-AI\logs\keeper-owner-stop.json     the same for all six

$Docs = $PSScriptRoot
if (-not $Docs) { $Docs = Split-Path -Parent $MyInvocation.MyCommand.Path }
$Forts = @(
    @{ L = 'A'; Dir = 'DF-AI';   Preset = 'War-hold' },
    @{ L = 'B'; Dir = 'DF-AI-B'; Preset = 'Monastery' },
    @{ L = 'C'; Dir = 'DF-AI-C'; Preset = 'Merchant city' },
    @{ L = 'D'; Dir = 'DF-AI-D'; Preset = 'Hermit hold' },
    @{ L = 'E'; Dir = 'DF-AI-E'; Preset = 'Deep mine' },
    @{ L = 'F'; Dir = 'DF-AI-F'; Preset = 'Garden fort' }
)
$Dashboard = Join-Path $Docs 'DF-AI\_stage\testrunner\dashboard.py'
$Runner = Join-Path $Docs 'DF-AI\_stage\testrunner\watch_tests.py'
$StatusLatest = Join-Path $Docs 'DF-AI\_stage\testrunner\results\status\status-latest.txt'
$MainLogs = Join-Path $Docs 'DF-AI\logs'
$GlobalOwnerStop = Join-Path $MainLogs 'keeper-owner-stop.json'

function Get-Folder($f) { Join-Path $Docs $f.Dir }
function Get-StopFile($f) { Join-Path (Get-Folder $f) 'logs\keeper-stop' }
function Get-OwnerStopFile($f) { Join-Path (Get-Folder $f) 'logs\keeper-owner-stop.json' }

# A keeper holds a lock on logs\keeper.lock while it runs (brain\util.py
# folder_lock), in the window's way, the watchdog's or an old console window.
function Test-Running($f) {
    $lock = Join-Path (Get-Folder $f) 'logs\keeper.lock'
    if (-not (Test-Path $lock)) { return $false }
    # the keeper locks the file's first byte (msvcrt.locking): try that byte,
    # sharing the file, so a keeper opening it meanwhile is never blocked
    try { $s = [System.IO.File]::Open($lock, 'Open', 'ReadWrite', 'ReadWrite') } catch { return $true }
    try {
        $s.Lock(0, 1)
        $s.Unlock(0, 1)
        return $false
    } catch {
        return $true
    } finally {
        $s.Close()
    }
}

# The keepers' python processes (and the hidden cmd around each), found by
# their command line: keeper.py and the fort's preset (the command line holds
# no folder: the keeper is started in it). Used by K and by the watchdog.
function Get-KeeperProcesses($f) {
    $procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='py.exe'" `
                   -ErrorAction SilentlyContinue)
    @($procs | Where-Object { $_.CommandLine -like '*keeper.py*' -and
                              ($_.CommandLine -like "*$($f.Preset)*" -or $_.CommandLine -like "*$(Get-Folder $f)\*") })
}

# The command the window and the watchdog both start a keeper with: hidden,
# through cmd so an error before the keeper's own log (a bad delivery, a crash
# at start) lands in logs\keeper-console.txt. Returns $false with no folder.
function Start-KeeperProcess($f) {
    $dir = Get-Folder $f
    if (-not (Test-Path $dir)) { return $false }
    New-Item -ItemType Directory -Force -Path (Join-Path $dir 'logs') | Out-Null
    $line = "python brain\keeper.py --revive --preset `"$($f.Preset)`" 2>> logs\keeper-console.txt"
    Start-Process -FilePath 'cmd.exe' -WorkingDirectory $dir -WindowStyle Hidden `
        -ArgumentList @('/d', '/c', $line) | Out-Null
    return $true
}

# the hourly status, hidden, in the background (it takes a few seconds)
function Start-StatusOnce {
    if (-not (Test-Path $Runner)) { return $false }
    Start-Process -FilePath 'python' -ArgumentList @("`"$Runner`"", '--status-once') `
        -WorkingDirectory (Split-Path $Runner) -WindowStyle Hidden | Out-Null
    return $true
}

function New-StopNote([string]$by, [string]$why) {
    if (-not $why) { $why = 'no reason given' }
    [ordered]@{ by = $by; why = $why; at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz') } |
        ConvertTo-Json -Compress
}

# UTF-8 with no BOM (the keeper reads either way)
function Write-NoteFile([string]$path, [string]$json) {
    New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
    [System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Write-StopFile($f, [string]$by, [string]$why) { Write-NoteFile (Get-StopFile $f) (New-StopNote $by $why) }
function Set-OwnerStop($f, [string]$by, [string]$why) { Write-NoteFile (Get-OwnerStopFile $f) (New-StopNote $by $why) }

# R and the window's start: the owner wants them running again
function Clear-OwnerStop {
    foreach ($f in $Forts) { Remove-Item -LiteralPath (Get-OwnerStopFile $f) -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $GlobalOwnerStop -Force -ErrorAction SilentlyContinue
}

# The owner-stop marker that holds this fort (its own, else the global one), or $null
function Get-OwnerStop($f) {
    foreach ($p in @((Get-OwnerStopFile $f), $GlobalOwnerStop)) {
        if (Test-Path -LiteralPath $p) { return Get-Item -LiteralPath $p }
    }
    return $null
}
