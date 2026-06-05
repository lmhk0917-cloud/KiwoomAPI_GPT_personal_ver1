param(
  [string]$TaskName = "KiwoomGPTPersonalMarketDayIntegration",
  [string]$ProjectDir = "C:\Users\lmhk2\PycharmProjects\KiwoomAPI_GPT_personal_ver1",
  [string]$StartTime = "08:55",
  [string]$OpenApiTaskName = "",
  [switch]$RequireExistingLogin,
  [switch]$AllowExistingKiwoom,
  [switch]$KillResidualBeforeStart,
  [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $ProjectDir "run_market_day_integration.ps1"

if ($Unregister) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "TASK_UNREGISTERED=$TaskName"
  } else {
    Write-Host "TASK_NOT_FOUND=$TaskName"
  }
  exit 0
}

if (-not (Test-Path -LiteralPath $scriptPath)) {
  throw "Launcher script not found: $scriptPath"
}

$argumentParts = @(
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  "`"$scriptPath`""
)

if ($RequireExistingLogin) {
  $argumentParts += "-RequireExistingLogin"
}

if ($AllowExistingKiwoom) {
  $argumentParts += "-AllowExistingKiwoom"
}

if ($KillResidualBeforeStart) {
  $argumentParts += "-KillResidualBeforeStart"
}

if ($OpenApiTaskName) {
  $argumentParts += "-OpenApiTaskName"
  $argumentParts += "`"$OpenApiTaskName`""
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument ($argumentParts -join " ") `
  -WorkingDirectory $ProjectDir

$trigger = New-ScheduledTaskTrigger `
  -Weekly `
  -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
  -At $StartTime

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 8)

$principal = New-ScheduledTaskPrincipal `
  -UserId $env:USERNAME `
  -LogonType Interactive `
  -RunLevel Limited

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description "Runs Kiwoom/OpenAI personal intraday integration test during Korean market hours." `
  -Force | Out-Null

Write-Host "TASK_REGISTERED=$TaskName"
Write-Host "TASK_START_TIME=$StartTime"
Write-Host "TASK_SCRIPT=$scriptPath"
Write-Host "TASK_MODE_REQUIRE_EXISTING_LOGIN=$RequireExistingLogin"
Write-Host "TASK_MODE_ALLOW_EXISTING_KIWOOM=$AllowExistingKiwoom"
Write-Host "TASK_MODE_KILL_RESIDUAL=$KillResidualBeforeStart"
Write-Host "TASK_OPENAPI_BOOTSTRAP=$OpenApiTaskName"
