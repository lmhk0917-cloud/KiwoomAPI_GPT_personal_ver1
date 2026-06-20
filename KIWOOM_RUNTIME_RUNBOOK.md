# Kiwoom Runtime Runbook

This runbook keeps the market-hour workflow explicit. Kiwoom OpenAPI+ is a
Windows desktop, COM, and QAxWidget runtime, so avoid duplicate login/session
attempts unless a runbook step says otherwise.

## Operating Rule

- Use one live Kiwoom session path at a time.
- Do not run `kiwoom_smoke_test.py` immediately before a full integration run.
- Use GPT as a risk/reward reviewer, not as an order trigger.
- Keep the personal project focused on the fixed watchlist:
  - `005930`
  - `000660`
- Do not add order execution to this project.

## Default Automatic Run

The scheduled task is:

```powershell
KiwoomGPTPersonalMarketDayIntegration
```

Expected action:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_market_day_integration.ps1 -AllowExistingKiwoom
```

This is the preferred regular-session path. It runs:

```text
main_timed_test.py
-> realtime ticks
-> event detection
-> signal generation
-> GPT analysis
-> Telegram filtering
-> paper-trade report
```

## Manual Run

When asked to manually log in or manually run the regular-session test, use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_intraday_supervisor.ps1
```

The wrapper now delegates to `run_market_day_integration.ps1 -AllowExistingKiwoom`
by default, so manual execution includes GPT and paper-trade feedback.

## Tick-Only Manual Run

Use tick-only mode only when the goal is raw collection, not GPT/paper feedback:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_intraday_supervisor.ps1 -TickOnly
```

Tick-only mode runs:

```text
intraday_collector_supervisor.py
-> kiwoom_realtime_collector.py
-> login
-> realtime registration
-> SQLite tick storage
```

It does not run event detection, GPT, notifications, or paper-trade evaluation.

Temporary guard: direct `intraday_collector_supervisor.py` execution is blocked
by default. Use the wrapper above when a tick-only run is explicitly needed.
This prevents stale launchers from starting a duplicate tick-only session before
the full integration task. Future packaging should focus on the OpenAPI
bootstrap/auto-login path, not on restoring unattended tick-only startup.

## Duplicate Run Guard

`run_market_day_integration.ps1` and `run_intraday_supervisor.ps1 -TickOnly` share:

```text
logs\market_day_integration.lock
```

If another market-day path is already active, the later process exits with code
`30` and prints one of:

```text
MARKET_DAY_ABORTED=lock_exists
SUPERVISOR_ABORTED=shared_lock_exists
```

This is intentional. It prevents the automatic task and a manual command from
competing for the same Kiwoom login/session.

## Preflight

Before a live test:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python preflight_check.py
```

Expected:

```text
PREFLIGHT_STATUS=ok
PREFLIGHT_RESIDUAL_COUNT=0
```

Do not use `--allow-inspection-unavailable` for live readiness. That option is
only for offline diagnostics.

## Success Criteria

For full integration:

```text
COLLECTOR_LOGIN_RESULT=0
COLLECTOR_REALTIME_REGISTER_RESULT=0
COLLECTOR_SAVED_TICK_COUNT > 0
analysis_results increased
event_logs increased when events occur
gpt_call_logs increased when GPT is eligible
paper_trade_results generated after enough forward ticks
```

For tick-only:

```text
COLLECTOR_LOGIN_RESULT=0
COLLECTOR_REALTIME_REGISTER_RESULT=0
COLLECTOR_SAVED_TICK_COUNT > 0
COLLECTOR_DB_DELTA=ticks:<positive number>
```

If login and realtime registration succeed but no ticks arrive after the
configured threshold, classify the result as:

```text
market_closed_or_no_ticks
```

Do not classify that case as `login_timeout`.

## Post-Run Checks

Read the newest logs:

```powershell
Get-ChildItem -Path logs -Filter "*YYYYMMDD*.log" | Sort-Object LastWriteTime -Descending
Get-Content -Path logs\market_day_integration_YYYYMMDD_HHMMSS.ps1.log -Tail 160
Get-Content -Path logs\main_timed_test_YYYYMMDD.log -Tail 160
Get-Content -Path logs\kiwoom_collector_YYYYMMDD.log -Tail 160
```

Run reports after a full integration run:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python gpt_call_report.py --limit 10
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python paper_trade_report.py --min-sample 5
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python today_test_report.py
```

## Safe Offline Validation

Run these from the project root:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python -m unittest tests.test_signal_logic
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python gpt_smoke_test.py
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python stability_check.py
```

`stability_check.py` includes AST syntax checking, simulation, GPT smoke, and
report smoke checks.

## Recovery Notes

- If a Kiwoom/OpenAPI update window appears, handle it manually before the live
  run.
- If `preflight_check.py` reports residual project Python processes, inspect
  them first. Do not kill processes unless the cleanup is intentional.
- If a stale `logs\market_day_integration.lock` is older than 12 hours, the
  wrappers remove it automatically.
- If `CommConnect()` times out repeatedly, check Kiwoom login windows, OpenAPI
  update dialogs, and `KIWOOM_LOGIN_TROUBLESHOOTING.md`.
