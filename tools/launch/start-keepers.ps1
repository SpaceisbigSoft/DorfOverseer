# DF AI Overseer: the six keepers in one window (22 Nov 2026).
#
# Starts each fort's keeper (brain\keeper.py --revive --preset ...) with no
# window of its own, 10 s apart, and shows the six forts in one view (the test
# runner's dashboard.py), refreshed every 30 s. It also writes the hourly status
# (watch_tests.py --status-once: results\status, what Claude Helper's status
# reads), so the test runner's window isn't needed beside it. Keys:
#   S  stop every keeper cleanly (each gets logs\keeper-stop: it stops as
#      Ctrl-C stops it, the fort left open)
#   R  start the keepers that aren't running
#   1-6  a fort's live log (A-F) in a window of its own
#   K  force-stop a keeper that won't stop (asks first; its fort isn't left open)
#   Q  close this window; the keepers keep running
# A keeper still running in an old console window is left alone (its lock).
# The old start-keepers.bat (six windows) still works.

$ErrorActionPreference = 'Continue'
$Docs = Split-Path -Parent $MyInvocation.MyCommand.Path
$Host.UI.RawUI.WindowTitle = 'DF AI Overseer: keepers'
$Dashboard = Join-Path $Docs 'DF-AI\_stage\testrunner\dashboard.py'
$Runner = Join-Path $Docs 'DF-AI\_stage\testrunner\watch_tests.py'
$NextStatus = (Get-Date).AddMinutes(5)      # the first a few minutes in, once the keepers run
$Refresh = 30
$Forts = @(
    @{ L = 'A'; Dir = 'DF-AI';   Preset = 'War-hold' },
    @{ L = 'B'; Dir = 'DF-AI-B'; Preset = 'Monastery' },
    @{ L = 'C'; Dir = 'DF-AI-C'; Preset = 'Merchant city' },
    @{ L = 'D'; Dir = 'DF-AI-D'; Preset = 'Hermit hold' },
    @{ L = 'E'; Dir = 'DF-AI-E'; Preset = 'Deep mine' },
    @{ L = 'F'; Dir = 'DF-AI-F'; Preset = 'Garden fort' }
)

function Get-Folder($f) { Join-Path $Docs $f.Dir }

# A keeper holds a lock on logs\keeper.lock while it runs (brain\util.py
# folder_lock), in this window's way or in an old console window.
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

function Start-Keeper($f) {
    $dir = Get-Folder $f
    if (-not (Test-Path $dir)) { Write-Host "  $($f.L): no folder $dir" -ForegroundColor Red; return }
    # (verifier) through a hidden cmd, so an error before the keeper's own log
    # (a bad delivery, a crash at start) lands in logs\keeper-console.txt
    New-Item -ItemType Directory -Force -Path (Join-Path $dir 'logs') | Out-Null
    $line = "python brain\keeper.py --revive --preset `"$($f.Preset)`" 2>> logs\keeper-console.txt"
    Start-Process -FilePath 'cmd.exe' -WorkingDirectory $dir -WindowStyle Hidden `
        -ArgumentList @('/d', '/c', $line) | Out-Null
    Write-Host "  $($f.L) $($f.Preset): started" -ForegroundColor Green
}

function Start-Missing {
    $first = $true
    foreach ($f in $Forts) {
        if (Test-Running $f) { Write-Host "  $($f.L) $($f.Preset): already running" -ForegroundColor DarkGray; continue }
        if (-not $first) { Start-Sleep -Seconds 10 }    # the games load one at a time
        Start-Keeper $f
        $first = $false
    }
}

function Stop-All {
    foreach ($f in $Forts) {
        if (Test-Running $f) {
            Set-Content -Path (Join-Path (Get-Folder $f) 'logs\keeper-stop') -Value 'stop' -Encoding ascii
        }
    }
    Write-Host ''
    Write-Host 'Asked every keeper to stop (each leaves its fort open). Waiting up to 90 s...' -ForegroundColor Yellow
    $until = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $until) {
        $left = @($Forts | Where-Object { Test-Running $_ })
        if ($left.Count -eq 0) { break }
        Write-Host ("  still running: " + (($left | ForEach-Object { $_.L }) -join ' ')) -ForegroundColor DarkGray
        Start-Sleep -Seconds 5
    }
    $left = @($Forts | Where-Object { Test-Running $_ })
    if ($left.Count -eq 0) { Write-Host 'Every keeper has stopped.' -ForegroundColor Green }
    else { Write-Host ("Still running: " + (($left | ForEach-Object { $_.L }) -join ' ') +
                       " (an old console keeper: close its window; a stuck hidden one: press K)") -ForegroundColor Red }
    Start-Sleep -Seconds 3
}

# (verifier) a stuck hidden keeper has no window to close: its python process
# found by its command line (keeper.py and its fort's preset) and ended. The
# fort isn't left open this way (S does that); only for one that won't stop.
function Kill-Stuck {
    $left = @($Forts | Where-Object { Test-Running $_ })
    if ($left.Count -eq 0) { Write-Host 'No keeper is running.' -ForegroundColor Green; Start-Sleep 2; return }
    Write-Host ("Force-stop the keepers still running (" + (($left | ForEach-Object { $_.L }) -join ' ') +
                ")? Their forts aren't left open this way. Y to go on: ") -ForegroundColor Yellow -NoNewline
    if ([Console]::ReadKey($true).KeyChar.ToString().ToUpper() -ne 'Y') { return }
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'"
    foreach ($f in $left) {
        foreach ($p in $procs) {
            if ($p.CommandLine -like '*keeper.py*' -and $p.CommandLine -like "*$($f.Preset)*") {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Host "  $($f.L) $($f.Preset): ended (process $($p.ProcessId))" -ForegroundColor Yellow
            }
        }
    }
    Start-Sleep -Seconds 3
}

function Show-Log($i) {
    $f = $Forts[$i]
    $log = Join-Path (Get-Folder $f) 'logs\unattended.log'
    $cmd = "`$Host.UI.RawUI.WindowTitle = 'Keeper $($f.L) $($f.Preset): live log'; " +
           "Get-Content -Path '$log' -Encoding UTF8 -Tail 40 -Wait"
    Start-Process -FilePath 'powershell' -ArgumentList @('-NoLogo', '-NoProfile', '-Command', $cmd) | Out-Null
}

# the hourly status, hidden, in the background (it takes a few seconds)
function Write-Status {
    Start-Process -FilePath 'python' -ArgumentList @("`"$Runner`"", '--status-once') `
        -WorkingDirectory (Split-Path $Runner) -WindowStyle Hidden | Out-Null
}

function Show-View {
    # the view clears the window and its scrollback itself (a taller-than-window
    # screen scrolled and left the Keepers line twice)
    & python $Dashboard --keepers
    $run = ($Forts | ForEach-Object { if (Test-Running $_) { "$($_.L) on" } else { "$($_.L) off" } }) -join '   '
    Write-Host ''
    Write-Host "Keepers:  $run" -ForegroundColor Cyan
    Write-Host ("Hourly status (alerts, Claude Helper's status): next " + $NextStatus.ToString('HH:mm')) -ForegroundColor DarkGray
    Write-Host '[S] stop all  [R] start stopped  [1-6] live log A-F  [K] force-stop stuck  [Q] close (keepers run on)' -ForegroundColor DarkGray
}

Clear-Host
Write-Host 'DF AI Overseer: starting the keepers that aren''t running (10 s apart)...' -ForegroundColor Cyan
Start-Missing
Start-Sleep -Seconds 2

while ($true) {
    if ((Get-Date) -ge $NextStatus) {
        Write-Status
        $NextStatus = (Get-Date).AddHours(1)
    }
    Show-View
    $until = (Get-Date).AddSeconds($Refresh)
    $key = $null
    while ((Get-Date) -lt $until -and -not $key) {
        if ([Console]::KeyAvailable) { $key = [Console]::ReadKey($true).KeyChar.ToString().ToUpper() }
        else { Start-Sleep -Milliseconds 200 }
    }
    switch ($key) {
        'S' { Stop-All }
        'K' { Kill-Stuck }
        'R' { Clear-Host; Write-Host 'Starting the stopped keepers...' -ForegroundColor Cyan; Start-Missing; Start-Sleep 2 }
        'Q' { exit }
        { $_ -in '1', '2', '3', '4', '5', '6' } { Show-Log ([int]$_ - 1) }
    }
}
