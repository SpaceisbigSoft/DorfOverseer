# DF AI Overseer: registers the keepers' watchdog in Task Scheduler (F5a, 27 Nov 2026).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File install-watchdog-task.ps1           (install or update)
#   powershell -NoProfile -ExecutionPolicy Bypass -File install-watchdog-task.ps1 -Remove   (uninstall)
#
# The task "DF AI keeper watchdog" runs keeper-watchdog.ps1 (beside this file)
# every 5 minutes for ever, as the current user, only while that user is logged
# on (Interactive: the keepers start Steam's DF, which needs the desktop
# session), hidden. Run it from a normal PowerShell as the player (no admin
# needed for a task of one's own). Task Scheduler's own history and
# DF-AI\logs\watchdog.log tell what it did.

param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$TaskName = 'DF AI keeper watchdog'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $Here 'keeper-watchdog.ps1'

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed the task '$TaskName'." -ForegroundColor Yellow
    } else {
        Write-Host "No task '$TaskName' to remove."
    }
    return
}

foreach ($need in @($Script, (Join-Path $Here 'keepers-common.ps1'))) {
    if (-not (Test-Path $need)) { throw "Not found: $need (copy it beside this file first)" }
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $Here `
    -Argument "-WindowStyle Hidden -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Script`""
# every 5 minutes from a minute from now, with no end (no -RepetitionDuration: indefinitely)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'DF AI Overseer: starts the six forts'' keepers that are not running (unless the owner stopped them) and writes the hourly status. tools\launch\keeper-watchdog.ps1' `
    -Force | Out-Null
Write-Host "Installed the task '$TaskName': every 5 minutes while $user is logged on, running $Script" -ForegroundColor Green
Write-Host "Its log: $(Join-Path $Here 'DF-AI\logs\watchdog.log'). Remove it with -Remove." -ForegroundColor DarkGray
