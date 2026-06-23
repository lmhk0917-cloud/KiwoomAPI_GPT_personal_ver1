@echo off
setlocal

set "PROJECT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%register_market_day_task.ps1" -AllowExistingKiwoom -KillResidualBeforeStart

endlocal
