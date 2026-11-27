# DF AI Overseer: the keepers' watchdog (F5a, 27 Nov 2026).
#
# Run by Task Scheduler every 5 minutes in the player's own logged-in session
# (Steam needs it; install-watchdog-task.ps1 registers it). Each run, once:
#   - each of the six forts whose keeper isn't running (its logs\keeper.lock
#     free and no keeper.py python process for it) is started exactly as the
#     keepers' window starts it (keepers-common.ps1 Start-KeeperProcess: hidden,
#     --revive --preset ...), 3 s apart, unless an owner-stop marker holds it
#     (<fort>\logs\keeper-owner-stop.json, or DF-AI\logs\keeper-owner-stop.json
#     for all six; the window's S and K write them, R and opening it clear them)
#   - the hourly status (watch_tests.py --status-once) when
#     results\status\status-latest.txt is older than 55 minutes, so the status
#     doesn't die with the keepers' window
# One line per action in DF-AI\logs\watchdog.log. Nothing here stops anything.
#   -DryRun  says what it would do (in the log and on screen), starts nothing

param([switch]$DryRun)

$ErrorActionPreference = 'Continue'
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'keepers-common.ps1')

$WatchLog = Join-Path $MainLogs 'watchdog.log'
$StatusAsked = Join-Path $MainLogs 'watchdog-status-asked'    # when this asked for the status last
$StatusMaxMin = 55
$RunEveryMin = 5

function Write-WatchLog([string]$text) {
    $line = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $(if ($DryRun) { '(dry run) ' } else { '' }) + $text
    try {
        New-Item -ItemType Directory -Force -Path $MainLogs | Out-Null
        if ((Test-Path $WatchLog) -and (Get-Item $WatchLog).Length -gt 1MB) {
            Move-Item -LiteralPath $WatchLog -Destination "$WatchLog.1" -Force
        }
        Add-Content -LiteralPath $WatchLog -Value $line -Encoding UTF8
    } catch { }
    if ($DryRun -or [Environment]::UserInteractive) { Write-Host $line }
}

# "by ..., why: ..." from a marker (fail soft: its file name)
function Get-NoteText($item) {
    try {
        $j = Get-Content -LiteralPath $item.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $t = @()
        if ($j.by) { $t += "by $($j.by)" }
        if ($j.why) { $t += "why: $($j.why)" }
        if ($j.at) { $t += "at $($j.at)" }
        if ($t.Count) { return ($t -join ', ') }
    } catch { }
    return $item.FullName
}

# a single run at a time (a slow run and the next one never both start keepers)
$mutex = New-Object System.Threading.Mutex($false, 'Local\DFAI-keeper-watchdog')
if (-not $mutex.WaitOne(0)) { exit 0 }
try {
    # --- the keepers
    $first = $true
    foreach ($f in $Forts) {
        $dir = Get-Folder $f
        if (-not (Test-Path $dir)) { continue }      # a fort not set up on this PC: nothing to say each run
        if (Test-Running $f) { continue }
        $procs = @(Get-KeeperProcesses $f)
        if ($procs.Count) { continue }               # starting or handing over (a fresh start): its lock comes
        $hold = Get-OwnerStop $f
        if ($hold) {
            # said once, the first run after the marker was written (not every 5 minutes)
            if ($hold.LastWriteTime -gt (Get-Date).AddMinutes(-($RunEveryMin + 1))) {
                Write-WatchLog "$($f.L) $($f.Preset): not running, left stopped (owner stop: $(Get-NoteText $hold))"
            }
            continue
        }
        if (-not $first) { Start-Sleep -Seconds 3 }  # the games load one at a time, as the window does
        $first = $false
        if ($DryRun) { Write-WatchLog "$($f.L) $($f.Preset): not running: would start it"; continue }
        if (Start-KeeperProcess $f) { Write-WatchLog "$($f.L) $($f.Preset): not running: started its keeper" }
        else { Write-WatchLog "$($f.L) $($f.Preset): not running and could not be started" }
    }

    # --- the hourly status
    $old = (Get-Date).AddMinutes(-$StatusMaxMin)
    $latest = if (Test-Path $StatusLatest) { (Get-Item $StatusLatest).LastWriteTime } else { [datetime]::MinValue }
    $asked = if (Test-Path $StatusAsked) { (Get-Item $StatusAsked).LastWriteTime } else { [datetime]::MinValue }
    # asked at most once in 55 minutes (a status that fails to write isn't asked for every 5)
    if ($latest -lt $old -and $asked -lt $old) {
        $age = if ($latest -eq [datetime]::MinValue) { 'none yet' } else { "$([int]((Get-Date) - $latest).TotalMinutes) min old" }
        if ($DryRun) { Write-WatchLog "hourly status: last ${age}: would write it" }
        elseif (Start-StatusOnce) {
            try { Set-Content -LiteralPath $StatusAsked -Value (Get-Date).ToString('o') -Encoding ascii } catch { }
            Write-WatchLog "hourly status: last ${age}: writing it (watch_tests.py --status-once)"
        } else { Write-WatchLog "hourly status: last ${age}, but no $Runner" }
    }
} catch {
    Write-WatchLog "error: $($_.Exception.Message)"
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
