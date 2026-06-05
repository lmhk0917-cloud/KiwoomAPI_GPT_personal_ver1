# Market Status Runbook

Use this when a market-wide interruption event occurs during a live test.

## Sell Sidecar

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python update_market_status.py --sell-sidecar --sidecar-started-at "2026-06-05 09:08:25" --summary "KOSPI sell-side sidecar triggered; program sell orders were paused for 5 minutes." --source "KRX/news/manual" --reliability "confirmed_news" --save-db
```

Effect:
- `market_context.json` gets `market_status.sidecar_status=triggered`.
- Running `main.py` reloads that file on the next analysis cycle.
- GPT receives `market_status` including sidecar direction and timestamps.
- Event detection emits `MARKET_SIDECAR_ACTIVE`.
- Deterministic signals penalize fresh long entries when direction is `sell`.

## Ended Sidecar

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python update_market_status.py --ended --sidecar-direction sell --sidecar-started-at "2026-06-05 09:08:25" --sidecar-ended-at "2026-06-05 09:13:25" --summary "KOSPI sell-side sidecar ended; keep risk penalty for the rest of the session." --source "KRX/news/manual" --reliability "confirmed_news" --save-db
```

## Reset

After the session or before the next trading day, reset the status:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python update_market_status.py --sidecar-status inactive --summary "No abnormal market-wide interruption state is currently recorded." --save-db
```
