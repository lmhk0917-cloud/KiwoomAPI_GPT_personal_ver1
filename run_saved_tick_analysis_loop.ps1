param(
  [string]$Conda = "C:\Users\lmhk2\anaconda3\Scripts\conda.exe",
  [string]$EnvName = "py37_32",
  [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
  [string]$Codes = "005930,000660",
  [int]$IntervalSeconds = 300,
  [string]$Until = "15:31"
)

$ErrorActionPreference = "Continue"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

$logDir = Join-Path $projectDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$loopLog = Join-Path $logDir ("saved_tick_analysis_loop_{0}.log" -f ($Date -replace "-", ""))

function Write-LoopLog {
  param([string]$Message)
  $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  $line | Tee-Object -FilePath $loopLog -Append
}

$untilTime = [datetime]::ParseExact(
  ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd"), $Until),
  "yyyy-MM-dd HH:mm",
  [Globalization.CultureInfo]::InvariantCulture
)

Write-LoopLog "SAVED_TICK_ANALYSIS_LOOP_STARTED date=$Date codes=$Codes interval=$IntervalSeconds until=$Until"

while ((Get-Date) -lt $untilTime) {
  Write-LoopLog "SAVED_TICK_ANALYSIS_RUN_START"
  & $Conda run --no-capture-output -n $EnvName python run_offline_today_analysis.py `
    --date $Date `
    --codes $Codes `
    --gpt `
    --force `
    --paper-limit 200 2>&1 | Tee-Object -FilePath $loopLog -Append
  $exitCode = $LASTEXITCODE
  Write-LoopLog "SAVED_TICK_ANALYSIS_RUN_EXIT=$exitCode"

  if ($exitCode -ne 0) {
    Write-LoopLog "SAVED_TICK_ANALYSIS_WARNING=nonzero_exit"
  }

  Start-Sleep -Seconds $IntervalSeconds
}

Write-LoopLog "SAVED_TICK_ANALYSIS_LOOP_FINISHED"
