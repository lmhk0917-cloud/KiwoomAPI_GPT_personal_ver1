param(
  [string]$ProjectDir = "C:\Users\lmhk2\PycharmProjects\Kiwoom_Core_Quant_Lab"
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
  $args = @(
    "-NoExit",
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "`"$PSCommandPath`"",
    "-ProjectDir",
    "`"$ProjectDir`""
  )
  Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList ($args -join " ")
  exit 0
}

Set-Location -LiteralPath $ProjectDir

$oldTasks = @(
  "KiwoomGPTPersonalMarketDayIntegration",
  "KiwoomOpenAPIBootstrap"
)
$newTasks = @(
  "KiwoomCoreQuantMarketDayIntegration",
  "KiwoomCoreQuantOpenAPIBootstrap"
)

foreach ($taskName in ($oldTasks + $newTasks)) {
  if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "TASK_UNREGISTERED=$taskName"
  } else {
    Write-Host "TASK_NOT_FOUND=$taskName"
  }
}

.\register_openapi_bootstrap_task.ps1
.\register_market_day_task.ps1 -OpenApiTaskName KiwoomCoreQuantOpenAPIBootstrap
.\check_openapi_bootstrap_task.ps1

Write-Host "RENAMED_SCHEDULED_TASK_MIGRATION_STATUS=ok"
