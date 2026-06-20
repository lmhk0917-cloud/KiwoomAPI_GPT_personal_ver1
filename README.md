# Kiwoom GPT Personal Market Analysis System

Kiwoom OpenAPI+ realtime market data and OpenAI GPT analysis are connected into
a personal Korean stock-market analysis system. The system collects live ticks,
builds multi-timeframe summaries, detects meaningful events, calls GPT only
when needed, and stores results for review and paper-trade feedback.

This is not an automated trading bot. The current goal is risk/reward analysis,
signal review, data collection, and validation.

## Project Goals

- Build a reliable realtime data pipeline under Kiwoom OpenAPI+ and 32-bit Python constraints.
- Store raw ticks, generated events, GPT calls, notifications, signal logs, and paper-trade evaluations in SQLite.
- Analyze a small fixed watchlist deeply instead of screening the full market broadly.
- Keep deterministic code responsible for collection, indicators, event detection, logging, and validation.
- Use GPT as a reviewer that explains risk/reward, conflicting evidence, and missing data.
- Improve signal quality through repeated market-session tests and paper-trade feedback.

## Technical Context

- OS: Windows
- Runtime: Anaconda 32-bit Python 3.7, environment `py37_32`
- Broker API: Kiwoom OpenAPI+
- GUI/Event bridge: PyQt5 + QAxWidget
- Database: SQLite
- AI API: OpenAI chat completions
- Tested model: `gpt-4o-mini`
- Notification: Telegram

Kiwoom OpenAPI+ requires a Windows desktop session and COM/QAxWidget
integration. The project is intentionally local-first and designed around
supervised market-hour runs.

## Current Scope

The project focuses on a small fixed watchlist:

- `005930`
- `000660`

Market benchmark ETFs are context inputs, not broad screening targets. Do not
expand this personal project into broad realtime screening unless that direction
is explicitly resumed.

## Core Features

- Realtime Kiwoom tick collection
- SQLite persistence for ticks, events, GPT calls, signals, notifications, paper-trade results, historical bars, and market context snapshots
- 1m / 3m / 5m OHLCV conversion
- Indicator summaries including MA, VWAP, RSI, MACD, ATR, Bollinger Band, volume ratios, and box range position
- Event-driven GPT calls with payload compression
- Cost-aware analysis using fee, tax, and slippage assumptions
- Telegram alert filtering
- Paper-trade evaluation loop
- PyQt dashboard for monitoring DB, signals, GPT logs, settings, and charts
- Market context hooks for investor flow, program trading, derivatives, macro data, news, disclosures, and public reaction
- Runbooks and diagnostics for Kiwoom login/session stability

## Data Flow

```text
Kiwoom realtime ticks
-> TickStore memory buffer and SQLite
-> 1m / 3m / 5m bars
-> indicators and market snapshots
-> event detection
-> validation signal generation
-> GPT payload compression
-> OpenAI chat completion
-> DB logging
-> Telegram / console notification
-> paper-trade evaluation
-> feedback into future analysis
```

## GPT Role

GPT does not receive the full raw DB. The system compresses the current analysis
state into a focused JSON payload.

GPT may receive:

- Current price, volume, intraday open/high/low, and strength
- 1m / 3m / 5m indicator summaries
- VWAP and MA distance percentages
- RSI, MACD, ATR, Bollinger, volume ratios, and box range position
- Detected events
- Local validation signal and risk level
- Market ETF, foreign/institution/program, derivatives, macro, news, and disclosure context when available
- Historical daily/minute bar summaries
- Paper-trade performance feedback
- Fee, tax, and slippage assumptions

GPT is a review layer. It should not be treated as the sole source of truth or
as an order trigger.

## Market-Hour Run Modes

The default automatic task is:

```powershell
KiwoomGPTPersonalMarketDayIntegration
```

It runs the full integration path:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_market_day_integration.ps1 -AllowExistingKiwoom
```

Full integration includes:

```text
realtime ticks
-> event detection
-> signal generation
-> GPT risk/reward analysis
-> Telegram filtering
-> paper-trade reporting
```

Manual login or manual regular-session requests should use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_intraday_supervisor.ps1
```

That wrapper delegates to the same full integration path by default, so manual
runs include GPT and paper-trade feedback.

Use tick-only mode only when the goal is raw tick collection:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_intraday_supervisor.ps1 -TickOnly
```

Tick-only mode logs in, registers realtime data, and stores ticks. It does not
run event detection, GPT analysis, Telegram alerts, or paper-trade evaluation.

Direct `intraday_collector_supervisor.py` execution is temporarily blocked by
default to prevent stale tick-only launchers from competing with the full
integration task. Explicit `-TickOnly` through the wrapper remains available.

The wrappers share:

```text
logs\market_day_integration.lock
```

If a manual run and the automatic task overlap, the later process exits with
code `30` instead of starting a second Kiwoom session.

## Offline Validation

Run these from the project root:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python -m unittest tests.test_signal_logic
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python gpt_smoke_test.py
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python stability_check.py
```

`stability_check.py` performs AST syntax checks, offline simulation, GPT smoke,
report smoke checks, and command help checks.

## Live-Run Readiness

Before a live run:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python preflight_check.py
```

Expected:

```text
PREFLIGHT_STATUS=ok
PREFLIGHT_RESIDUAL_COUNT=0
```

Do not use `--allow-inspection-unavailable` for live readiness. It is only for
offline diagnostics.

## Post-Run Reports

After a full integration run:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python gpt_call_report.py --limit 10
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python paper_trade_report.py --min-sample 5
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python today_test_report.py
```

For tick-only runs, only raw tick storage should be evaluated.

## Focused Dashboard

For a Toss-style read-only operating view of the Kiwoom DB:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launch_focused_dashboard.ps1 -RefreshSec 30
```

This UI does not log in, collect ticks, call GPT, send alerts, or place orders.
It reads SQLite only and shows runtime health, focused symbol rows, recent GPT
analysis, events, signals, paper-trade feedback, and market context snapshots.
The focused symbols are loaded from `watchlists/domestic_kr.json` by default.
Use `-Symbols 005930,000660` only as a temporary override.

To export an HTML snapshot without opening the desktop window:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_focused_dashboard.py --export-html
```

## Security Notes

The repository intentionally excludes local secrets and runtime data:

- `.env`
- SQLite databases
- logs
- exports
- local market context state
- IDE files
- Python cache
- archive data

Use `.env.example` as a template and create a local `.env` file for credentials.

## Packaging Position

Packaging into an executable is not the immediate priority. Keep live-session
stability first. Do not move the root-level Kiwoom runtime scripts or scheduler
entrypoints until another full regular-session integration run passes.

## Portfolio Note

This project is valuable less because it predicts stocks and more because it
demonstrates work across a difficult integration boundary:

- legacy Windows COM API
- realtime event-driven data collection
- SQLite schema design
- market-data feature engineering
- LLM prompt/payload design
- logging and observability
- alerting
- paper-trade validation
- UI monitoring
- operational runbooks

The current limitation list is intentional. It documents the next engineering
problems clearly and keeps the next steps concrete.
