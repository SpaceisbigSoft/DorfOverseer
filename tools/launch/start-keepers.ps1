# DF AI Overseer: the six keepers in one window (22 Nov 2026).
#
# Starts each fort's keeper (brain\keeper.py --revive --preset ...) with no
# window of its own, 3 s apart, and shows the six forts in one view (the test
# runner's dashboard.py), refreshed every 30 s. It also writes the hourly status
# (watch_tests.py --status-once: results\status, what Claude Helper's status
# reads), so the test runner's window isn't needed beside it. Keys:
#   S  stop every keeper cleanly (asks Y first; each gets logs\keeper-stop
#      saying who and why: it stops as Ctrl-C stops it, the fort left open,
#      and logs who asked). Also writes each fort's logs\keeper-owner-stop.json
#      so the watchdog (keeper-watchdog.ps1, Task Scheduler) leaves them stopped
#   R  start the keepers that aren't running (clears the owner-stop markers;
#      so does opening this window)
#   1-6  a fort's live log (A-F) in a window of its own
#   K  force-stop a keeper that won't stop (asks first; its fort isn't left open)
#   Q  close this window; the keepers keep running
# A keeper still running in an old console window is left alone (its lock).
# The old start-keepers.bat (six windows) still works.

$ErrorActionPreference = 'Continue'
# the forts, the paths, Test-Running, the start command and the markers (F5a:
# shared with keeper-watchdog.ps1)
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'keepers-common.ps1')
$Host.UI.RawUI.WindowTitle = 'DF AI Overseer: keepers'
$NextStatus = (Get-Date).AddMinutes(5)      # the first a few minutes in, once the keepers run
$Refresh = 30
function Start-Keeper($f) {
    # (verifier) through a hidden cmd (keepers-common.ps1 Start-KeeperProcess)
    if (-not (Start-KeeperProcess $f)) { Write-Host "  $($f.L): no folder $(Get-Folder $f)" -ForegroundColor Red; return }
    Write-Host "  $($f.L) $($f.Preset): started" -ForegroundColor Green
}

function Start-Missing {
    Clear-OwnerStop     # (F5a) the owner starts them: the watchdog may restart them again
    $first = $true
    foreach ($f in $Forts) {
        if (Test-Running $f) { Write-Host "  $($f.L) $($f.Preset): already running" -ForegroundColor DarkGray; continue }
        if (-not $first) { Start-Sleep -Seconds 3 }    # the games load one at a time (23 Nov: 3 s, was 10)
        Start-Keeper $f
        $first = $false
    }
}

function Stop-All {
    # (F5a) asked first (26 Nov 15:39: all six stopped at once, nobody knew why)
    Write-Host ''
    Write-Host 'Stop all six keepers? (Y/N) ' -ForegroundColor Yellow -NoNewline
    if ([Console]::ReadKey($true).KeyChar.ToString().ToUpper() -ne 'Y') { Write-Host 'N: nothing stopped.'; Start-Sleep 1; return }
    Write-Host 'Y'
    $why = Read-Host 'Why (a few words, Enter to skip)'
    $by = 'keepers window key S'
    # the owner-stop markers first, so the watchdog never starts one meanwhile
    foreach ($f in $Forts) { if (Test-Path (Get-Folder $f)) { Set-OwnerStop $f $by $why } }
    foreach ($f in $Forts) {
        if (Test-Running $f) { Write-StopFile $f $by $why }
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
    foreach ($f in $left) {
        # (F5a) the watchdog leaves a force-stopped keeper stopped too (R starts it)
        Set-OwnerStop $f 'keepers window key K' 'force-stopped (would not stop)'
        foreach ($p in (Get-KeeperProcesses $f)) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  $($f.L) $($f.Preset): ended (process $($p.ProcessId))" -ForegroundColor Yellow
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
function Write-Status { Start-StatusOnce | Out-Null }

function Show-View {
    # the view clears the window and its scrollback itself (a taller-than-window
    # screen scrolled and left the Keepers line twice)
    & python $Dashboard --keepers
    $run = ($Forts | ForEach-Object { if (Test-Running $_) { "$($_.L) on" } else { "$($_.L) off" } }) -join '   '
    Write-Host ''
    Write-Host "Keepers:  $run" -ForegroundColor Cyan
    Write-Host ("Hourly status (alerts, Claude Helper's status): next " + $NextStatus.ToString('HH:mm')) -ForegroundColor DarkGray
    Write-Host '[S] stop all (asks)  [R] start stopped  [1-6] live log A-F  [K] force-stop stuck  [Q] close (keepers run on)' -ForegroundColor DarkGray
}

Clear-Host
Write-Host 'DF AI Overseer: starting the keepers that aren''t running (3 s apart)...' -ForegroundColor Cyan
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
