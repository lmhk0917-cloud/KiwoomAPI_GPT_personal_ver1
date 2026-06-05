param(
  [string[]]$Targets = @(
    "C:\OpenAPI\opstarter.exe",
    "C:\OpenAPI\KOAStudioSA.exe"
  ),
  [switch]$Disable,
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$layersPath = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"

if (-not (Test-Path -LiteralPath $layersPath)) {
  if (-not $ValidateOnly) {
    New-Item -Path $layersPath -Force | Out-Null
  }
}

foreach ($target in $Targets) {
  if (-not (Test-Path -LiteralPath $target)) {
    Write-Host "RUNASINVOKER_TARGET_MISSING=$target"
    continue
  }

  if ($ValidateOnly) {
    $current = Get-ItemProperty -Path $layersPath -Name $target -ErrorAction SilentlyContinue
    $value = if ($current) { $current.$target } else { "" }
    Write-Host "RUNASINVOKER_TARGET=$target"
    Write-Host "RUNASINVOKER_CURRENT=$value"
    continue
  }

  if ($Disable) {
    Remove-ItemProperty -Path $layersPath -Name $target -ErrorAction SilentlyContinue
    Write-Host "RUNASINVOKER_DISABLED=$target"
  } else {
    New-ItemProperty -Path $layersPath -Name $target -Value "RUNASINVOKER" -PropertyType String -Force | Out-Null
    Write-Host "RUNASINVOKER_ENABLED=$target"
  }
}
