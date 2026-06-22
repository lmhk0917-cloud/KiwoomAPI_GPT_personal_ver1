param(
  [switch]$TickOnly,
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$ProjectDir = "C:\Users\lmhk2\PycharmProjects\Kiwoom_Core_Quant_Lab"
$Conda = "C:\Users\lmhk2\anaconda3\Scripts\conda.exe"

Set-Location $ProjectDir
$env:QT_QPA_PLATFORM = "windows"

if (-not $TickOnly) {
  $args = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    ".\run_market_day_integration.ps1",
    "-AllowExistingKiwoom"
  )

  if ($ValidateOnly) {
    $args += "-ValidateOnly"
  }

  Write-Host "SUPERVISOR_MODE=market_day_integration"
  & powershell.exe @args
  exit $LASTEXITCODE
}

Write-Host "SUPERVISOR_MODE=tick_only"

$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$LockPath = Join-Path $LogDir "market_day_integration.lock"
if (Test-Path -LiteralPath $LockPath) {
  $lockAgeMinutes = ((Get-Date) - (Get-Item -LiteralPath $LockPath).LastWriteTime).TotalMinutes
  if ($lockAgeMinutes -lt 720) {
    Write-Host "SUPERVISOR_ABORTED=shared_lock_exists"
    Write-Host "LOCK_PATH=$LockPath"
    exit 30
  }

  Write-Host "SUPERVISOR_STALE_LOCK_REMOVED=True"
  Remove-Item -LiteralPath $LockPath -Force
}

Set-Content -LiteralPath $LockPath -Value $PID -Encoding ASCII

try {
  $env:KIWOOM_ALLOW_TICK_ONLY = "1"
  & $Conda run --no-capture-output -n py37_32 python intraday_collector_supervisor.py `
    --until 15:31 `
    --market-open 09:00 `
    --no-tick-skip-after 09:10 `
    --retry-delay-sec 120 `
    --login-timeout-sec 45 `
    --attempt-seconds 0 `
    --allow-tick-only-runtime
  exit $LASTEXITCODE
}
finally {
  if (Test-Path -LiteralPath $LockPath) {
    $lockOwner = Get-Content -LiteralPath $LockPath -ErrorAction SilentlyContinue
    if ($lockOwner -eq "$PID") {
      Remove-Item -LiteralPath $LockPath -Force
    }
  }
}
