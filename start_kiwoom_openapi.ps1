param(
  [string]$OpenApiDir = "C:\OpenAPI",
  [string]$StarterExe = "opstarter.exe",
  [string]$DisableFlagPath = "",
  [int]$WaitSeconds = 30,
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

if (-not $DisableFlagPath) {
  $DisableFlagPath = Join-Path $PSScriptRoot "openapi_bootstrap.disabled"
}

function Test-KiwoomProcessRunning {
  $names = @(
    "opstarter",
    "khmini",
    "khministarter",
    "nkmini",
    "nkministarter",
    "khopenapi",
    "koastudiosa",
    "koastudio"
  )

  foreach ($name in $names) {
    if (Get-Process -Name $name -ErrorAction SilentlyContinue) {
      return $true
    }
  }

  return $false
}

if (-not (Test-Path -LiteralPath $OpenApiDir)) {
  throw "OpenAPI directory not found: $OpenApiDir"
}

$starterPath = Join-Path $OpenApiDir $StarterExe
if (-not (Test-Path -LiteralPath $starterPath)) {
  throw "OpenAPI starter not found: $starterPath"
}

if ($ValidateOnly) {
  Write-Host "OPENAPI_VALIDATE_ONLY=True"
  Write-Host "OPENAPI_STARTER=$starterPath"
  Write-Host "OPENAPI_RUNNING=$(Test-KiwoomProcessRunning)"
  Write-Host "OPENAPI_DISABLE_FLAG=$DisableFlagPath"
  Write-Host "OPENAPI_BOOTSTRAP_DISABLED=$(Test-Path -LiteralPath $DisableFlagPath)"
  exit 0
}

if (Test-Path -LiteralPath $DisableFlagPath) {
  Write-Host "OPENAPI_START_SKIPPED=disabled"
  Write-Host "OPENAPI_DISABLE_FLAG=$DisableFlagPath"
  exit 0
}

if (Test-KiwoomProcessRunning) {
  Write-Host "OPENAPI_START_SKIPPED=already_running"
  exit 0
}

Write-Host "OPENAPI_STARTER=$starterPath"
Start-Process -FilePath $starterPath -WorkingDirectory $OpenApiDir -WindowStyle Normal

if ($WaitSeconds -gt 0) {
  Start-Sleep -Seconds $WaitSeconds
}

Write-Host "OPENAPI_RUNNING=$(Test-KiwoomProcessRunning)"
