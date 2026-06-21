param(
  [string]$Python = "C:\Users\lmhk2\anaconda3\python.exe",
  [switch]$SkipToss,
  [switch]$SkipContest
)

$ErrorActionPreference = "Continue"
$startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$TossRoot = "C:\Users\lmhk2\Documents\New project\toss_trading_runtime"
$ContestRoot = "C:\Users\lmhk2\PycharmProjects\KiwoomAPI_GPT_contestver"

Write-Host "POST_REBOOT_READINESS_STARTED=$startedAt"
Write-Host "KIWOOM_ROOT=$Root"

function Check-Path($Path) {
  if (Test-Path -LiteralPath $Path) {
    $item = Get-Item -LiteralPath $Path
    Write-Host "PATH_OK $Path size=$($item.Length) mtime=$($item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
  } else {
    Write-Host "PATH_MISSING $Path"
  }
}

Check-Path "C:\OpenAPI\khopenapi.ocx"
Check-Path "C:\OpenAPI\KHOpenAPI.ocx"
Check-Path "C:\OpenAPI\system\MultiLogin.ini"
Check-Path "C:\OpenAPI\MultiLogin.ini"

Write-Host "COM_PROGID_QUERY"
cmd /c reg query "HKCR\KHOPENAPI.KHOpenAPICtrl.1\CLSID"

Write-Host "COM_WOW6432_CLSID_QUERY"
cmd /c reg query "HKCR\WOW6432Node\CLSID\{A1574A0D-6BFA-4BD7-9020-DED88711818D}" /s

Write-Host "RESIDUAL_PROCESS_CHECK"
Get-Process |
  Where-Object {
    $_.ProcessName -like "Kiwoom*" -or
    $_.ProcessName -like "opstarter*" -or
    $_.ProcessName -like "nkmini*" -or
    $_.ProcessName -like "khmini*"
  } |
  Select-Object ProcessName,Id,StartTime |
  Format-Table -AutoSize

Write-Host "KIWOOM_PERSONAL_UNIT_TEST_START"
Push-Location $Root
& $Python -m unittest discover -s tests -p "test*.py"
$kiwoomExit = $LASTEXITCODE
Pop-Location
Write-Host "KIWOOM_PERSONAL_UNIT_TEST_EXIT=$kiwoomExit"

if (-not $SkipToss) {
  Write-Host "TOSS_RUNTIME_TEST_START"
  Push-Location $TossRoot
  & $Python tests\test_toss_runtime.py
  $tossExit = $LASTEXITCODE
  Pop-Location
  Write-Host "TOSS_RUNTIME_TEST_EXIT=$tossExit"
} else {
  $tossExit = 0
  Write-Host "TOSS_RUNTIME_TEST_SKIPPED=True"
}

if (-not $SkipContest) {
  Write-Host "CONTEST_OFFLINE_TEST_START"
  Push-Location $ContestRoot
  & $Python kiwoom_tr_queue_offline_test.py
  $contest1 = $LASTEXITCODE
  & $Python order_dry_run_test.py
  $contest2 = $LASTEXITCODE
  & $Python quant_trading_offline_test.py
  $contest3 = $LASTEXITCODE
  & $Python screening_offline_test.py
  $contest4 = $LASTEXITCODE
  Pop-Location
  Write-Host "CONTEST_OFFLINE_TEST_EXITS=$contest1,$contest2,$contest3,$contest4"
} else {
  $contest1 = 0
  $contest2 = 0
  $contest3 = 0
  $contest4 = 0
  Write-Host "CONTEST_OFFLINE_TEST_SKIPPED=True"
}

$failed = @($kiwoomExit, $tossExit, $contest1, $contest2, $contest3, $contest4) | Where-Object { $_ -ne 0 }
if ($failed.Count -gt 0) {
  Write-Host "POST_REBOOT_READINESS_STATUS=failed"
  exit 1
}

Write-Host "POST_REBOOT_READINESS_STATUS=ok"
exit 0
