param(
  [string]$ProjectDir = "C:\Users\lmhk2\PycharmProjects\Kiwoom_Core_Quant_Lab",
  [string]$Conda = "C:\Users\lmhk2\anaconda3\Scripts\conda.exe",
  [string]$CondaEnv = "py37_32",
  [string]$MarketOpen = "09:00",
  [string]$MarketClose = "15:31",
  [int]$LoginCheckSeconds = 45,
  [string]$OpenApiTaskName = "",
  [int]$OpenApiTaskWaitSeconds = 60,
  [int]$MaxRestarts = 3,
  [int]$RestartDelaySeconds = 20,
  [switch]$RequireExistingLogin,
  [switch]$AllowExistingKiwoom,
  [switch]$KillResidualBeforeStart,
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

function Get-TodayDateTime([string]$HHmm) {
  $parts = $HHmm.Split(":")
  if ($parts.Count -ne 2) {
    throw "Invalid HH:mm time: $HHmm"
  }

  return (Get-Date).Date.AddHours([int]$parts[0]).AddMinutes([int]$parts[1])
}

if (-not (Test-Path -LiteralPath $ProjectDir)) {
  throw "Project directory not found: $ProjectDir"
}

if (-not (Test-Path -LiteralPath $Conda)) {
  throw "conda.exe not found: $Conda"
}

$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$LockPath = Join-Path $LogDir "market_day_integration.lock"
$Now = Get-Date
$Stamp = $Now.ToString("yyyyMMdd_HHmmss")
$TranscriptPath = Join-Path $LogDir "market_day_integration_$Stamp.ps1.log"

if (Test-Path -LiteralPath $LockPath) {
  $lockAgeMinutes = ((Get-Date) - (Get-Item -LiteralPath $LockPath).LastWriteTime).TotalMinutes
  if ($lockAgeMinutes -lt 720) {
    Write-Host "MARKET_DAY_ABORTED=lock_exists"
    Write-Host "LOCK_PATH=$LockPath"
    exit 30
  }

  Remove-Item -LiteralPath $LockPath -Force
}

Set-Content -LiteralPath $LockPath -Value $PID -Encoding ASCII

try {
  Start-Transcript -Path $TranscriptPath -Append | Out-Null

  Set-Location $ProjectDir
  $env:QT_QPA_PLATFORM = "windows"

  $openAt = Get-TodayDateTime $MarketOpen
  $closeAt = Get-TodayDateTime $MarketClose
  $now = Get-Date

  if ($now -lt $openAt -and -not $ValidateOnly) {
    $waitSeconds = [int][Math]::Ceiling(($openAt - $now).TotalSeconds)
    Write-Host "MARKET_DAY_WAIT_UNTIL_OPEN_SECONDS=$waitSeconds"
    Start-Sleep -Seconds $waitSeconds
    $now = Get-Date
  }

  if ($now -ge $closeAt -and -not $ValidateOnly) {
    Write-Host "MARKET_DAY_ABORTED=after_market_close"
    Write-Host "MARKET_CLOSE=$MarketClose"
    exit 0
  }

  $durationBaseTime = $now
  if ($ValidateOnly -and $now -lt $openAt) {
    $durationBaseTime = $openAt
  }

  $durationMinutes = [int][Math]::Ceiling(($closeAt - $durationBaseTime).TotalMinutes)
  if ($durationMinutes -lt 1) {
    $durationMinutes = 1
  }

  Write-Host "MARKET_DAY_PROJECT_DIR=$ProjectDir"
  Write-Host "MARKET_DAY_CONDA_ENV=$CondaEnv"
  Write-Host "MARKET_DAY_DURATION_MINUTES=$durationMinutes"
  Write-Host "MARKET_DAY_TRANSCRIPT=$TranscriptPath"
  Write-Host "MARKET_DAY_MAX_RESTARTS=$MaxRestarts"
  Write-Host "MARKET_DAY_RESTART_DELAY_SECONDS=$RestartDelaySeconds"

  if ($OpenApiTaskName) {
    Write-Host "MARKET_DAY_OPENAPI_TASK=$OpenApiTaskName"
    if ($ValidateOnly) {
      Write-Host "MARKET_DAY_OPENAPI_TASK_VALIDATE_ONLY=True"
    } else {
      $openApiTask = Get-ScheduledTask -TaskName $OpenApiTaskName -ErrorAction SilentlyContinue
      if ($openApiTask) {
        Start-ScheduledTask -TaskName $OpenApiTaskName
        Write-Host "MARKET_DAY_OPENAPI_TASK_STARTED=True"
        if ($OpenApiTaskWaitSeconds -gt 0) {
          Start-Sleep -Seconds $OpenApiTaskWaitSeconds
        }
      } else {
        Write-Host "MARKET_DAY_OPENAPI_TASK_MISSING=$OpenApiTaskName"
      }
    }
  }

  if ($ValidateOnly) {
    $args = @(
      "run",
      "--no-capture-output",
      "-n",
      $CondaEnv,
      "python",
      "main_timed_test.py",
      "--minutes",
      "$durationMinutes",
      "--paper-report",
      "--paper-report-min-sample",
      "5",
      "--login-check-seconds",
      "$LoginCheckSeconds"
    )

    if ($RequireExistingLogin) {
      $args += "--require-existing-login"
      $args += "--allow-existing-kiwoom"
    } elseif ($AllowExistingKiwoom) {
      $args += "--allow-existing-kiwoom"
    }

    if ($KillResidualBeforeStart) {
      $args += "--kill-residual"
    }

    Write-Host "MARKET_DAY_VALIDATE_ONLY=True"
    Write-Host "MARKET_DAY_COMMAND=$Conda $($args -join ' ')"
    exit 0
  }

  $attempt = 0
  $finalExitCode = 0

  while ($true) {
    $attempt += 1
    $attemptNow = Get-Date

    if ($attemptNow -ge $closeAt) {
      Write-Host "MARKET_DAY_STOP_REASON=market_closed_before_attempt"
      $finalExitCode = 0
      break
    }

    $attemptMinutes = [int][Math]::Ceiling(($closeAt - $attemptNow).TotalMinutes)
    if ($attemptMinutes -lt 1) {
      $attemptMinutes = 1
    }

    $attemptArgs = @(
      "run",
      "--no-capture-output",
      "-n",
      $CondaEnv,
      "python",
      "main_timed_test.py",
      "--minutes",
      "$attemptMinutes",
      "--paper-report",
      "--paper-report-min-sample",
      "5",
      "--login-check-seconds",
      "$LoginCheckSeconds"
    )

    if ($RequireExistingLogin) {
      $attemptArgs += "--require-existing-login"
      $attemptArgs += "--allow-existing-kiwoom"
    } elseif ($AllowExistingKiwoom) {
      $attemptArgs += "--allow-existing-kiwoom"
    }

    if ($KillResidualBeforeStart -and $attempt -eq 1) {
      $attemptArgs += "--kill-residual"
    }

    Write-Host "MARKET_DAY_ATTEMPT=$attempt"
    Write-Host "MARKET_DAY_ATTEMPT_DURATION_MINUTES=$attemptMinutes"
    Write-Host "MARKET_DAY_ATTEMPT_STARTED_AT=$($attemptNow.ToString('yyyy-MM-dd HH:mm:ss'))"

    & $Conda @attemptArgs
    $exitCode = $LASTEXITCODE
    $finalExitCode = $exitCode

    Write-Host "MARKET_DAY_ATTEMPT_EXIT_CODE=$exitCode"

    if ($exitCode -eq 0) {
      Write-Host "MARKET_DAY_STOP_REASON=normal_exit"
      break
    }

    $afterAttempt = Get-Date
    if ($afterAttempt -ge $closeAt) {
      Write-Host "MARKET_DAY_STOP_REASON=abnormal_exit_after_market_close"
      break
    }

    if ($attempt -gt $MaxRestarts) {
      Write-Host "MARKET_DAY_STOP_REASON=max_restarts_exceeded"
      break
    }

    Write-Host "MARKET_DAY_RESTART_SCHEDULED=True"
    Write-Host "MARKET_DAY_RESTART_AFTER_EXIT_CODE=$exitCode"
    Write-Host "MARKET_DAY_RESTART_DELAY_SECONDS=$RestartDelaySeconds"
    Start-Sleep -Seconds $RestartDelaySeconds
  }

  Write-Host "MARKET_DAY_EXIT_CODE=$finalExitCode"
  exit $finalExitCode
}
finally {
  try {
    Stop-Transcript | Out-Null
  } catch {
  }

  if (Test-Path -LiteralPath $LockPath) {
    Remove-Item -LiteralPath $LockPath -Force
  }
}
