@echo off
rem The six keepers in one PowerShell window (start-keepers.ps1). The old start-keepers.bat still opens six.
mode con: cols=120 lines=42 >nul 2>&1
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-keepers.ps1"
