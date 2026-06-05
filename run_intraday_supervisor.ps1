$ErrorActionPreference = "Stop"

$ProjectDir = "C:\Users\lmhk2\PycharmProjects\KiwoomAPI_GPT_personal_ver1"
$Conda = "C:\Users\lmhk2\anaconda3\Scripts\conda.exe"

Set-Location $ProjectDir
$env:QT_QPA_PLATFORM = "windows"

& $Conda run --no-capture-output -n py37_32 python intraday_collector_supervisor.py `
  --until 15:31 `
  --market-open 09:00 `
  --no-tick-skip-after 09:10 `
  --retry-delay-sec 120 `
  --login-timeout-sec 45 `
  --attempt-seconds 300
