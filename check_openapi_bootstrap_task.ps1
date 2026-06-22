param(
  [string]$OpenApiTaskName = "KiwoomCoreQuantOpenAPIBootstrap",
  [string]$MarketTaskName = "KiwoomCoreQuantMarketDayIntegration"
)

$ErrorActionPreference = "Stop"

function Write-TaskStatus([string]$TaskName) {
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if (-not $task) {
    Write-Host "TASK_MISSING=$TaskName"
    return
  }

  $info = Get-ScheduledTaskInfo -TaskName $TaskName
  Write-Host "TASK_FOUND=$TaskName"
  Write-Host "TASK_STATE=$($task.State)"
  Write-Host "TASK_RUNLEVEL=$($task.Principal.RunLevel)"
  Write-Host "TASK_LAST_RUN=$($info.LastRunTime)"
  Write-Host "TASK_LAST_RESULT=$($info.LastTaskResult)"
  Write-Host "TASK_NEXT_RUN=$($info.NextRunTime)"
}

Write-TaskStatus $OpenApiTaskName
Write-TaskStatus $MarketTaskName
