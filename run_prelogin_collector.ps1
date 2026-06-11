$ErrorActionPreference = "Stop"

$ProjectDir = "C:\Users\lmhk2\PycharmProjects\KiwoomAPI_GPT_personal_ver1"
$Conda = "C:\Users\lmhk2\anaconda3\Scripts\conda.exe"

Set-Location $ProjectDir
$env:QT_QPA_PLATFORM = "windows"

& $Conda run --no-capture-output -n py37_32 python kiwoom_realtime_collector.py `
  --seconds 32400 `
  --login-timeout-sec 90
