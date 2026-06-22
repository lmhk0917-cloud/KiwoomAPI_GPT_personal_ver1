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

$logDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("install_openapi_tasks_admin_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $logPath -Append | Out-Null

try {
  Write-Host "ADMIN_INSTALL_STARTED=True"
  Write-Host "PROJECT_DIR=$ProjectDir"
  Write-Host "ADMIN_INSTALL_LOG=$logPath"

  .\register_openapi_bootstrap_task.ps1
  .\register_market_day_task.ps1 -OpenApiTaskName KiwoomCoreQuantOpenAPIBootstrap
  .\check_openapi_bootstrap_task.ps1

  Write-Host ""
  Write-Host "ADMIN_INSTALL_FINISHED=True"
  Write-Host "If both tasks are shown as TASK_FOUND, registration is complete."
} catch {
  Write-Host "ADMIN_INSTALL_FAILED=True"
  Write-Host "ADMIN_INSTALL_ERROR=$($_.Exception.Message)"
  throw
} finally {
  try {
    Stop-Transcript | Out-Null
  } catch {
  }
}
