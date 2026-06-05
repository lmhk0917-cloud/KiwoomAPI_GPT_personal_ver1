# 2026-06-01 Morning Test Readiness

## Scheduled Run

- OpenAPI helper task: `KiwoomOpenAPIBootstrap`
  - next run: `2026-06-01 08:45`
  - state: `Ready`
  - note: automatic OpenAPI bootstrap remains disabled by `openapi_bootstrap.disabled`
- Market-day integration task: `KiwoomGPTPersonalMarketDayIntegration`
  - next run: `2026-06-01 08:55`
  - state: `Ready`
  - launcher option: `-AllowExistingKiwoom`
  - runtime window: wait until `09:00`, then run until `15:31`

## Manual Action Before Market Open

1. Keep the PC powered on and stay logged in to the Windows desktop session.
2. Open Kiwoom OpenAPI manually before `08:55` when possible.
3. Approve the Windows administrator confirmation dialog if it appears.
4. Complete any Kiwoom login confirmation dialog.
5. Do not start a second Kiwoom/OpenAPI login session.

## Verified On 2026-05-31

- `preflight_check.py`: `PREFLIGHT_STATUS=ok`, residual process count `0`
- Python AST check: `79` files passed
- `.env`: OpenAI API key, Telegram bot token, and Telegram chat ID configured
- `stability_check.py --count 180 --cycle-ticks 30`: passed
- operating DB: `data/ticks.db`, `528572416` bytes
- operating DB ticks: `2572891`
- GPT calls: `500` success, `0` failed
- recent logs: no matching `Traceback`, `ERROR`, `Exception`, or login failure pattern

## Morning Verification Order

1. Confirm manual OpenAPI login is complete.
2. Confirm `KiwoomGPTPersonalMarketDayIntegration` starts at `08:55`.
3. After `09:00`, confirm `data/ticks.db` grows.
4. Confirm `ticks`, `event_logs`, `analysis_results`, and `gpt_call_logs` increase.
5. Confirm Telegram receives only filtered event messages.

## Failure Triage

1. Run `python preflight_check.py` in the `py37_32` conda environment.
2. Check the newest `logs/market_day_integration_*.ps1.log`.
3. Check the newest `logs/main_timed_test_*.log`.
4. If login succeeds but ticks remain unchanged after market open, treat it as a realtime registration or market-session issue before changing GPT logic.
