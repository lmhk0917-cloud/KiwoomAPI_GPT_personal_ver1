@echo off
setlocal

set "PROJECT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%install_openapi_tasks_admin.ps1" -ProjectDir "%PROJECT_DIR%"

endlocal
