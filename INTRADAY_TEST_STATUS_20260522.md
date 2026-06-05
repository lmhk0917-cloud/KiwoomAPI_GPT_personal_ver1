# Intraday Test Status - 2026-05-22

## Current Status

- Test time: around 13:29 KST
- Goal: verify manual Kiwoom OpenAPI connection, then run intraday test until market close
- Result: not started

## Key Evidence

The safe existing-login test was run:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python main_timed_test.py --seconds 60 --require-existing-login --allow-existing-kiwoom
```

Output summary:

```text
PREFLIGHT_STATUS=ok
PREFLIGHT_RESIDUAL_COUNT=0
키움 연결 상태 확인: 0
키움 기존 연결 필요: 현재 미연결이므로 로그인 요청 생략
TIMED_TEST_ABORTED=existing_login_not_confirmed
DB_COUNTS_DELTA=ticks:0
```

## Interpretation

The user manually opened/logged into Kiwoom, but the Python `QAxWidget`
OpenAPI control did not see an active OpenAPI session. `GetConnectState()`
returned `0`, so the test correctly avoided calling `CommConnect()` and did
not start the long intraday run.

## Current DB State

- `ticks`: latest `2026-05-21 15:20:52.442559`
- No 2026-05-22 realtime tick persistence confirmed yet

## Next Safe Test

Run this first:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python main_timed_test.py --seconds 60 --require-existing-login --allow-existing-kiwoom
```

Only if it prints `키움 연결 상태 확인: 1`, continue with a longer run.

If it still prints `0`, the manual Kiwoom login is not visible to the Python
OpenAPI control. In that case, use a clean PC/Kiwoom state and let the Python
process perform the OpenAPI login itself, or verify Kiwoom OpenAPI auto-login
settings.

## 13:32 KST Recheck

The user manually connected Kiwoom again and the safe existing-login test was
run again:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python main_timed_test.py --seconds 60 --require-existing-login --allow-existing-kiwoom
```

Result:

```text
PREFLIGHT_STATUS=ok
키움 연결 상태 확인: 0
키움 기존 연결 필요: 현재 미연결이므로 로그인 요청 생략
TIMED_TEST_ABORTED=existing_login_not_confirmed
DB_COUNTS_DELTA=ticks:0
```

Conclusion: the manually opened Kiwoom session is still not visible to the
Python `QAxWidget` OpenAPI control. Long intraday testing was not started.

## 13:37 KST Minimal Collector Attempt

A dedicated minimal collector was added:

- `kiwoom_realtime_collector.py`

It avoids GPT, Telegram, TR context, and the `main.py` analysis loop. It only
creates `QAxWidget`, logs in, registers realtime stock trade FIDs, and stores
ticks through `TickStore`.

Command:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_realtime_collector.py --seconds 60 --login-timeout-sec 45
```

Result:

```text
COLLECTOR_OCX_STATUS=created
COLLECTOR_CONNECT_STATE_BEFORE=0
COLLECTOR_LOGIN_REQUESTED=True
COLLECTOR_LOGIN_TIMEOUT=True
COLLECTOR_CONNECT_STATE_TIMEOUT=0
COLLECTOR_DB_DELTA=ticks:0
```

Interpretation: the minimal OpenAPI collector could create the OCX, but Kiwoom
did not deliver `OnEventConnect` within the login timeout. No 2026-05-22 tick
persistence was confirmed.

## 13:46 KST Recheck After Closing KOA Studio

The user closed KOA Studio manually. Process inspection no longer showed
`KOAStudioSA.exe`, and preflight reported no residual sessions:

```text
PREFLIGHT_STATUS=ok
PREFLIGHT_RESIDUAL_COUNT=0
```

The collector was retried:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_realtime_collector.py --seconds 60 --login-timeout-sec 45
```

Result:

```text
COLLECTOR_OCX_STATUS=created
COLLECTOR_CONNECT_STATE_BEFORE=0
COLLECTOR_LOGIN_REQUESTED=True
COLLECTOR_LOGIN_TIMEOUT=True
COLLECTOR_CONNECT_STATE_TIMEOUT=0
COLLECTOR_DB_DELTA=ticks:0
```

The minimal smoke test was also retried and did not return within the command
timeout. This confirms the issue is not in the main app or DB write path; the
current Windows/Kiwoom session is not delivering the OpenAPI login callback.

Recommended next step: reboot or fully reset the Kiwoom/OpenAPI environment,
do not start KOA Studio manually, and run `kiwoom_realtime_collector.py` as the
first OpenAPI process.

## Post-Close Supervisor Setup

At 18:08 KST the regular session was already closed. The supervisor was tested
with a past stop time and exited correctly:

```text
SUPERVISOR_STOP_REASON=market_close_reached
SUPERVISOR_DB_END=ticks:261324
```

Added files:

- `intraday_collector_supervisor.py`: retries the minimal collector until the
  configured close time.
- `run_intraday_supervisor.ps1`: one-command launcher for the next regular
  session.

Local OpenAPI update evidence:

- `C:\OpenAPI\khopenapi.ocx` modified at `2026-05-21 17:49:00`
- `C:\OpenAPI\opcommapi.dll` modified at `2026-05-21 17:49:00`
- `C:\OpenAPI\opcomms.dll` modified at `2026-05-21 17:49:00`
- `C:\OpenAPI\system\opcomms.ini` has update flags enabled:
  `DOWNLOAD=1`, `MODULE_DOWNLOAD=1`, `DAT_DOWNLOAD=1`
- `C:\OpenAPI\system\MultiLogin.ini` contains `LOCKMODE use=1`

Next regular-session command:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_intraday_supervisor.ps1
```

## 18:29 KST Post-Close Login Recheck

After market close, the minimal collector was run again to verify whether the
OpenAPI login itself works. Tick reception was not expected because the regular
session had ended.

Command:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_realtime_collector.py --seconds 5 --login-timeout-sec 20
```

Result:

```text
COLLECTOR_OCX_STATUS=created
COLLECTOR_LOGIN_REQUEST_RETURN=0
COLLECTOR_LOGIN_RESULT=0
COLLECTOR_CONNECT_STATE_AFTER=1
COLLECTOR_REALTIME_REGISTER_RESULT=0
COLLECTOR_REALTIME_EVENT_COUNT=0
COLLECTOR_SAVED_TICK_COUNT=0
COLLECTOR_DB_DELTA=ticks:0
```

Interpretation:

- Kiwoom OpenAPI login is currently working.
- Realtime registration is currently working.
- Tick persistence still needs a regular-session test.
- `COLLECTOR_SAVED_TICK_COUNT=0` is acceptable after market close.

## Offline Stability Check

The offline stability check was strengthened to include:

- Python compile check
- `preflight_check.py`
- deterministic simulation through `simulate_debug.py`
- GPT payload preview
- GPT call report
- paper-trade quality report
- CLI validation for online-test helper scripts

Command:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python stability_check.py --count 360 --cycle-ticks 30
```

Result:

```text
STABILITY_CHECK_RESULT=PASS
ticks: 1080
analysis_results: 33
event_logs: 93
gpt_call_logs: 33
signal_logs: 33
paper_trade_results: 0
notification_logs: 0
```

## Current Readiness

Status: ready for the next regular-session online test.

Confirmed:

- Offline simulation path works.
- SQLite write path works.
- Event, signal, GPT-call-log, and analysis-result tables are populated in
  simulation.
- Actual Kiwoom OpenAPI login works after market close.
- Actual realtime registration call returns success after market close.

Not yet confirmed:

- Live `OnReceiveRealData` events during the regular session.
- Live tick persistence into `data\ticks.db` for 2026-05-22 or later.
- Full `main.py` analysis loop on live data after the minimal collector succeeds.

## Next Online Test Procedure

Use this sequence for the next regular-session test.

1. Before the market opens, do not manually start KOA Studio, Hero/HTS, or
   another Kiwoom OpenAPI test unless necessary.
2. Run preflight:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python preflight_check.py
```

Expected:

```text
PREFLIGHT_STATUS=ok
PREFLIGHT_RESIDUAL_COUNT=0
```

Warnings about unknown non-project Python processes can be reviewed, but they
do not block the run unless they are known Kiwoom/project processes.

3. Start the regular-session supervisor:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_intraday_supervisor.ps1
```

4. Success criteria:

```text
COLLECTOR_LOGIN_RESULT=0
COLLECTOR_REALTIME_REGISTER_RESULT=0
COLLECTOR_SAVED_TICK_COUNT > 0
SUPERVISOR_ATTEMPT_DELTA ticks > 0
```

Market-open/no-tick handling:

- The supervisor waits before `09:00` and does not start collector attempts
  early.
- After `09:10`, if Kiwoom login and realtime registration both succeed but
  no ticks are saved, the run is classified as
  `SUPERVISOR_STOP_REASON=market_closed_or_no_ticks`.
- This is treated as a market-closed/no-session skip, not as a login failure.
- This avoids maintaining a local holiday calendar while still distinguishing
  holidays/no-session days from OpenAPI login problems.

5. If the supervisor reports `login_timeout`, run:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_login_diagnostics.py --tail-lines 80
```

Then follow `KIWOOM_LOGIN_TROUBLESHOOTING.md`.

6. Only after the minimal collector confirms live tick persistence, proceed to
   the broader integration path through `main_timed_test.py` or `main.py`.

## Operational Notes

- Do not run `kiwoom_smoke_test.py` immediately before the supervisor during a
  regular-session test. Kiwoom OpenAPI is sensitive to duplicate or sequential
  login sessions.
- Avoid running multiple `conda run` commands in parallel. This environment has
  shown temporary-file collisions when conda commands overlap.
- The personal project remains analysis/storage/notification only. No order
  placement path is enabled here.
