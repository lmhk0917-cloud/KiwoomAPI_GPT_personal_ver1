# Kiwoom GPT Personal Market Analysis System

Kiwoom OpenAPI+ realtime market data and OpenAI GPT analysis are connected into a personal Korean stock-market analysis system. The project focuses on collecting live ticks, converting them into multi-timeframe indicators, detecting meaningful events, calling GPT only when needed, and storing every result for review and paper-trade feedback.

This is not an automated trading bot. The current goal is risk/reward analysis, signal review, data collection, and validation.

## Project Goals

- Build a working realtime data pipeline under the constraints of Kiwoom OpenAPI+ and 32-bit Python.
- Store raw ticks, generated events, GPT calls, notifications, and paper-trade evaluations in SQLite.
- Analyze selected high-interest symbols deeply rather than screen the whole market broadly.
- Use GPT as a reasoning and review layer, while deterministic code handles data collection, indicator calculation, event detection, and logging.
- Improve signal quality through repeated market-session tests and paper-trade feedback.

## Technical Context

- OS: Windows
- Runtime: Anaconda 32-bit Python 3.7
- Broker API: Kiwoom OpenAPI+
- GUI/Event bridge: PyQt5 + QAxWidget
- Database: SQLite
- AI API: OpenAI chat completions
- Tested model: `gpt-4o-mini`
- Notification: Telegram

Kiwoom OpenAPI+ requires a Windows desktop session and COM/QAxWidget integration. Because of that, this project is intentionally local-first and designed around supervised market-hour runs.

## Core Features

- Realtime Kiwoom tick collection
- SQLite persistence for:
  - ticks
  - analysis results
  - event logs
  - GPT call logs
  - notification logs
  - signal logs
  - paper-trade results
  - historical bars
  - market context snapshots
- 1m / 3m / 5m OHLCV conversion
- Technical indicators:
  - MA5 / MA20 / MA60
  - MA distance from current price
  - VWAP and VWAP distance
  - RSI
  - MACD
  - ATR
  - Bollinger Band
  - volume ratios
  - box-range position
- Event-driven GPT calls
- GPT input compression
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

## GPT Input Design

GPT does not receive the full raw DB. The system compresses the current analysis state into a focused JSON payload.

Included examples:

- Current price, volume, intraday open/high/low, strength
- 1m / 3m / 5m indicator summaries
- VWAP distance percentage
- MA5 / MA20 / MA60 distance percentages
- RSI, MACD, ATR, Bollinger, volume ratios
- Detected events
- Local validation signal and risk level
- Market ETF context such as KODEX 200 and KODEX KOSDAQ150
- Foreign/institution/program flow when available
- Derivatives and macro context when available
- Short selling and credit context when available
- Historical daily/minute bar summaries
- Paper-trade performance feedback
- Fee, tax, and slippage assumptions

This design keeps token usage controlled while preserving the quantitative evidence needed for short-term risk/reward judgment.

## Current Scope

The current project intentionally focuses on a small set of selected symbols, mainly Samsung Electronics and SK Hynix, with market benchmark ETFs used as context. This is a deliberate design choice: the priority is deeper understanding of selected names and market regime behavior, not broad realtime screening.

## Current Limitations and Improvement Plan

The project is already operational, but it is still an evolving research system. The most important part of the work now is not adding more indicators blindly, but improving reliability, data quality, validation logic, and operating discipline.

### 1. Kiwoom Runtime Dependency

Current limitation:

- Kiwoom OpenAPI+ requires a Windows desktop environment, GUI login state, and QAxWidget.
- Live testing depends on market hours and the stability of the local session.
- Native Qt/Kiwoom crashes can happen outside normal Python exception handling.

Improvement plan:

- Keep strengthening supervisor scripts and restart logic.
- Separate data collection, analysis, and reporting more clearly.
- Maintain preflight checks for residual sessions, login state, DB health, and recent tick growth.
- Preserve offline simulation tests so code quality can be checked even outside market hours.

This is a realistic systems constraint, and the project already reflects the ability to work with awkward external APIs instead of assuming an ideal cloud-only environment.

### 2. Signal Quality and Market Regime Awareness

Current limitation:

- Early rebound signals are still weaker than confirmed pullback or trend-continuation signals.
- A falling market can produce many technically tempting but low-quality rebound candidates.
- Some event types need more evaluated samples before thresholds can be trusted.

Improvement plan:

- Treat `WATCH_PULLBACK` as the primary high-quality long setup until rebound signals prove themselves.
- Require stronger confirmation for `WATCH_REBOUND`, especially:
  - index ETF 3m/5m recovery
  - VWAP reclaim
  - reduced foreign/program selling
  - volume expansion
  - orderbook confirmation
- Use paper-trade results to adjust confidence scores and thresholds.
- Track performance by action type, symbol, time window, and market regime.

The intent is to avoid overfitting one indicator and build a feedback loop that makes each market session more informative.

### 3. GPT Role Definition

Current limitation:

- GPT is good at integrating evidence, but it should not be the sole source of truth.
- If too much raw data is sent, token cost, latency, and noise increase.
- If too little context is sent, GPT may miss market-regime risk.

Improvement plan:

- Keep deterministic code responsible for raw calculations, event detection, and validation.
- Use GPT as a reviewer that explains risk/reward, conflicting evidence, and missing data.
- Improve payload compression so GPT gets more useful quantitative context without receiving raw noise.
- Add structured outputs later so GPT responses can be scored and compared more easily.

This project treats LLMs as one layer in a larger decision system, not as a magic trading oracle.

### 4. Historical Data and Backtesting

Current limitation:

- Realtime data is accumulating, but robust strategy evaluation needs more labeled history.
- Current paper-trade evaluation is useful but still sample-size limited.
- Raw ticks are valuable but expensive to keep forever without an archive policy.

Improvement plan:

- Continue collecting live data for representative market regimes.
- Backfill daily/minute bars where Kiwoom TR limits allow.
- Evaluate signals over 5m, 10m, 30m, and 60m horizons.
- Compare action types across different market conditions.
- Later, convert the data into training/evaluation datasets for model comparison.

The longer-term direction is a measured research pipeline: collect, label, evaluate, adjust, and only then automate more.

### 5. UI and Productization

Current limitation:

- The dashboard exists, but it is still primarily an engineering/debugging tool.
- Configuration editing and visual review can be improved.
- Packaging into an executable is not yet the main priority because live data stability matters first.

Improvement plan:

- Improve the dashboard around the actual workflow:
  - watchlist editing
  - threshold editing
  - signal review
  - GPT call history
  - paper-trade performance
  - chart and indicator visualization
- Package the app only after the live-session workflow is stable.
- Keep sensitive credentials outside the repository and runtime logs.

This shows the intended path from prototype to usable personal application without hiding current rough edges.

### 6. Future Advanced Direction

Current limitation:

- GPT currently receives compressed summaries, not the full raw historical dataset.
- Full raw-data reasoning would require more storage, retrieval, and modeling infrastructure.

Improvement plan:

- Store raw data locally and summarize it for current GPT calls.
- Later introduce retrieval over raw historical patterns.
- Compare current setups with similar past setups.
- Add dedicated statistical or ML models for short-horizon risk prediction.
- Keep GPT as an explanation and synthesis layer above deterministic/quantitative models.

The long-term architecture is not "send everything to GPT." It is "build a data system where GPT can inspect the right evidence at the right time."

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

Use `.env.example` as a template and create a local `.env` file for actual credentials.

## Typical Local Workflow

```powershell
# Run offline stability checks
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python stability_check.py --count 180 --cycle-ticks 30

# Run GPT smoke test
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python gpt_smoke_test.py

# Inspect GPT call history
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python gpt_call_report.py --limit 5
```

Live Kiwoom tests require the correct Windows desktop session, Kiwoom OpenAPI+ installation, login state, and market-hour availability.

## Portfolio Note

This project is valuable less because it "predicts stocks" and more because it demonstrates work across a difficult integration boundary:

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

The current limitation list is intentional. It documents the next engineering problems clearly and shows the direction for solving them.
