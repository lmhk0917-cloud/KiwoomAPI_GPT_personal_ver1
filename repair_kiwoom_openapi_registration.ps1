# Kiwoom OpenAPI+ 32-bit OCX repair helper.
#
# Run this only from an Administrator PowerShell after closing KOA Studio,
# Kiwoom login windows, Hero/HTS windows, and project Python processes.
# This script does not start trading or call the project application.

$ErrorActionPreference = "Stop"

Write-Host "Kiwoom OpenAPI+ registration repair started."

$ocxPath = "C:\OpenAPI\khopenapi.ocx"
$regsvr32Path = "C:\Windows\SysWOW64\regsvr32.exe"

if (-not (Test-Path -LiteralPath $ocxPath)) {
    throw "Missing Kiwoom OCX: $ocxPath"
}

if (-not (Test-Path -LiteralPath $regsvr32Path)) {
    throw "Missing 32-bit regsvr32: $regsvr32Path"
}

Write-Host "Registering 32-bit OCX:"
Write-Host "  $ocxPath"

& $regsvr32Path $ocxPath

Write-Host "Registration command finished."
Write-Host "Recommended next steps:"
Write-Host "  1. Reboot Windows."
Write-Host "  2. Run preflight_check.py from the project."
Write-Host "  3. Run kiwoom_realtime_collector.py for a short login test."
