# Data Storage Policy

This project is the hot store for Korean-market live evidence.

## Current Role

- `data/ticks.db` is the operating SQLite DB.
- `ticks` stores Kiwoom realtime ticks.
- `historical_bars` stores Kiwoom TR daily/minute bars and imported shared daily reference bars.
- Shared 10-year data is imported only as `historical_bars.timeframe='day'` with `source='shared_yahoo_history_daily'`.
- Shared daily data must not be copied into `ticks`.

## Retention Direction

Recommended once a local SSD is installed:

- Keep the latest 3-6 months of `ticks` in the hot DB.
- Archive older `ticks` by month or quarter into read-only SQLite files.
- Keep `historical_bars`, `signal_logs`, and `paper_trade_results` longer because they are compact and useful for feedback.
- Back up `data/ticks.db` before any archive or vacuum operation.

## Dry-Run Report

Use this command before changing storage:

```powershell
C:\Users\lmhk2\anaconda3\python.exe tools\db_retention_report.py --hot-days 120
```

The report is read-only. It only counts rows that would be archive candidates.

## SSD Move Guidance

Do not move the live project while Kiwoom/Toss collectors or dashboards are running.

Preferred approach:

1. Stop collectors, dashboards, schedulers, and Python processes.
2. Make a normal backup of the current folders.
3. Copy the project folders to the SSD.
4. Run tests from the copied folders.
5. Update shortcuts, scheduled tasks, and any absolute paths.
6. Keep the old copy read-only for a few days before deleting it.
