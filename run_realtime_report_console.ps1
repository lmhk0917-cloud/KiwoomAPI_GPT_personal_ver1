param(
  [string]$Python = "C:\Users\lmhk2\anaconda3\python.exe",
  [int]$IntervalSeconds = 15,
  [switch]$ShowRawLog
)

$ErrorActionPreference = "Continue"
try {
  chcp 65001 | Out-Null
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

$query = @"
import sqlite3, app_paths
conn = sqlite3.connect(app_paths.DEFAULT_DB_PATH)
cur = conn.cursor()
def one(sql):
    return cur.execute(sql).fetchone()
print("DB:", app_paths.DEFAULT_DB_PATH)
print("ticks:", one("select count(*) from ticks")[0])
print("latest_tick:", one("select code,trade_time,received_at,price from ticks order by id desc limit 1"))
print("analysis_results:", one("select count(*) from analysis_results")[0])
print("latest_analysis:", cur.execute("select id,code,analyzed_at,current_price from analysis_results order by id desc limit 2").fetchall())
print("event_logs:", one("select count(*) from event_logs")[0])
print("latest_events:", cur.execute("select id,code,detected_at,event_type,gpt_requested,skip_reason from event_logs order by id desc limit 4").fetchall())
print("signal_logs:", one("select count(*) from signal_logs")[0])
print("latest_signals:", cur.execute("select id,code,detected_at,action_hint,confidence_score from signal_logs order by id desc limit 4").fetchall())
print("gpt_call_logs:", one("select count(*) from gpt_call_logs")[0])
print("latest_gpt:", one("select id,started_at,status,requested_count,codes,total_tokens,error_message from gpt_call_logs order by id desc limit 1"))
print("paper_trade_results:", one("select count(*) from paper_trade_results")[0])
try:
    print("latest_paper:", one("select id,code,evaluated_at,horizon_min,return_pct,outcome from paper_trade_results order by id desc limit 1"))
except Exception as exc:
    print("latest_paper: unavailable", exc)
conn.close()
"@

while ($true) {
  Clear-Host
  Write-Host "Kiwoom realtime report" -ForegroundColor Cyan
  Write-Host ("updated_at: {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
  Write-Host ""
  & $Python -c $query

  if ($ShowRawLog) {
    Write-Host ""
    Write-Host "main.py recent raw log" -ForegroundColor Cyan
    Write-Host "Raw log may look garbled on some Windows consoles." -ForegroundColor Yellow
    $mainLog = Get-ChildItem .\logs -Filter "main_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($mainLog) {
      Get-Content -Encoding UTF8 $mainLog.FullName -Tail 30
    } else {
      Write-Host "No main log found."
    }
  }

  Write-Host ""
  Write-Host ("refresh every {0}s - Ctrl+C to stop this report window" -f $IntervalSeconds) -ForegroundColor DarkGray
  Start-Sleep -Seconds $IntervalSeconds
}
