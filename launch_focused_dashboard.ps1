param(
  [string]$Symbols = "",
  [int]$RefreshSec = 30,
  [string]$Python = "C:\Users\lmhk2\anaconda3\Scripts\conda.exe"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$DashboardArgs = @("kiwoom_focused_dashboard.py", "--refresh-sec", $RefreshSec)
if ($Symbols.Trim()) {
  $DashboardArgs += @("--symbols", $Symbols)
}

if ($Python -like "*conda.exe") {
  & $Python run --no-capture-output -n py37_32 python @DashboardArgs
} else {
  & $Python @DashboardArgs
}

exit $LASTEXITCODE
