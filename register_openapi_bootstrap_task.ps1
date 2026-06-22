param(
  [string]$TaskName = "KiwoomCoreQuantOpenAPIBootstrap",
  [string]$ProjectDir = "C:\Users\lmhk2\PycharmProjects\Kiwoom_Core_Quant_Lab",
  [string]$StartTime = "08:45",
  [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $ProjectDir "start_kiwoom_openapi.ps1"

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
  throw "OpenAPI bootstrap script not found: $scriptPath"
}

$argumentParts = @(
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  "`"$scriptPath`""
)

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
  -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

$principal = New-ScheduledTaskPrincipal `
  -UserId $env:USERNAME `
  -LogonType Interactive `
  -RunLevel Highest

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description "Starts Kiwoom OpenAPI+ starter before the personal intraday integration task." `
  -Force | Out-Null

Write-Host "TASK_REGISTERED=$TaskName"
Write-Host "TASK_START_TIME=$StartTime"
Write-Host "TASK_SCRIPT=$scriptPath"
Write-Host "TASK_RUNLEVEL=Highest"
