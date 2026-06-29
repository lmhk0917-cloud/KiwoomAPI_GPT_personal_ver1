"""Retry Kiwoom realtime collection until the regular session ends.

This supervisor does not create a QAxWidget itself. It repeatedly launches the
minimal collector as a child process, records DB deltas, and stops at the
configured market close time. It avoids privileged cleanup so it can run
unattended without extra Codex permission prompts.
"""

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

from app_paths import DEFAULT_DB_PATH, setup_runtime_logging
from preflight_check import print_preflight_report, run_preflight
from shared_context_auto_export import export_shared_context


TABLES = [
    "ticks",
    "analysis_results",
    "event_logs",
    "gpt_call_logs",
    "signal_logs",
    "paper_trade_results",
    "notification_logs",
]


def count_rows(db_path):
    """Return compact row counts for important runtime tables."""
    counts = {}
    conn = sqlite3.connect(db_path)
    try:
        for table_name in TABLES:
            try:
                counts[table_name] = conn.execute(
                    "SELECT COUNT(*) FROM {}".format(table_name)
                ).fetchone()[0]
            except sqlite3.Error:
                counts[table_name] = None
        latest = conn.execute("SELECT MAX(received_at) FROM ticks").fetchone()[0]
        counts["latest_tick_received_at"] = latest
    finally:
        conn.close()
    return counts


def print_counts(label, counts):
    """Print row counts in a stable one-line format."""
    fields = ["{}:{}".format(key, counts.get(key)) for key in TABLES]
    fields.append("latest_tick_received_at:{}".format(counts.get("latest_tick_received_at")))
    print("{}={}".format(label, ",".join(fields)))


def seconds_until_close(close_hhmm):
    """Return seconds until today's configured close time."""
    return seconds_until_time(close_hhmm)


def seconds_until_time(hhmm):
    """Return seconds until today's configured local HH:MM time."""
    now = datetime.now()
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return int((target - now).total_seconds())


def is_time_reached(hhmm):
    """Return True after today's configured local HH:MM time."""
    return seconds_until_time(hhmm) <= 0


def run_collector_attempt(attempt, run_seconds, login_timeout_sec):
    """Run one collector child process and stream its output to this log."""
    command = [
        sys.executable,
        "kiwoom_realtime_collector.py",
        "--seconds",
        str(run_seconds),
        "--login-timeout-sec",
        str(login_timeout_sec),
        "--require-ticks",
    ]

    print("SUPERVISOR_ATTEMPT={} command={}".format(attempt, " ".join(command)))
    started_at = datetime.now()
    timeout = run_seconds + login_timeout_sec + 90

    try:
        completed = subprocess.run(
            command,
            cwd=os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=timeout,
        )
        output = completed.stdout or ""
        for line in output.splitlines():
            print("COLLECTOR_CHILD={}".format(line))
        duration = (datetime.now() - started_at).total_seconds()
        print("SUPERVISOR_ATTEMPT_RESULT={} exit_code={} duration_sec={:.1f}".format(
            attempt,
            completed.returncode,
            duration,
        ))
        return completed.returncode, output
    except subprocess.TimeoutExpired as exc:
        output = exc.output or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        for line in output.splitlines():
            print("COLLECTOR_CHILD={}".format(line))
        print("SUPERVISOR_ATTEMPT_RESULT={} timeout=True".format(attempt))
        return 124, output


def parse_args():
    parser = argparse.ArgumentParser(description="Retry Kiwoom collector until market close.")
    parser.add_argument("--until", default="15:31", help="Local HH:MM stop time.")
    parser.add_argument("--retry-delay-sec", type=int, default=120)
    parser.add_argument("--login-timeout-sec", type=int, default=45)
    parser.add_argument(
        "--attempt-seconds",
        type=int,
        default=0,
        help=(
            "Collector run length per successful login. "
            "Use 0 to keep one collector alive until market close."
        ),
    )
    parser.add_argument("--allow-existing-kiwoom", action="store_true")
    parser.add_argument("--market-open", default="09:00", help="Local HH:MM before which collector attempts wait.")
    parser.add_argument(
        "--no-tick-skip-after",
        default="09:10",
        help="After this local HH:MM, login/register success with no ticks is treated as market closed/no session.",
    )
    parser.add_argument(
        "--allow-tick-only-runtime",
        action="store_true",
        help="Temporary guard bypass for an explicitly requested tick-only supervisor run.",
    )
    return parser.parse_args()


def is_tick_only_runtime_allowed(args):
    """Return True only when the temporary direct-run guard is explicitly bypassed."""
    return bool(args.allow_tick_only_runtime or os.environ.get("KIWOOM_ALLOW_TICK_ONLY") == "1")


def normalize_attempt_seconds(args):
    """Keep the temporary tick-only supervisor from relogging every few minutes."""
    if args.allow_tick_only_runtime and args.attempt_seconds and args.attempt_seconds > 0:
        print("SUPERVISOR_ATTEMPT_SECONDS_OVERRIDDEN={}=>0".format(args.attempt_seconds))
        args.attempt_seconds = 0
    return args.attempt_seconds


def main():
    args = parse_args()
    setup_runtime_logging("intraday_supervisor")
    if not is_tick_only_runtime_allowed(args):
        print("SUPERVISOR_ABORTED=tick_only_disabled")
        print("SUPERVISOR_GUARD=explicit_tick_only_required")
        return 30
    normalize_attempt_seconds(args)

    print("SUPERVISOR_STARTED_AT={}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("SUPERVISOR_UNTIL={}".format(args.until))
    print("SUPERVISOR_MARKET_OPEN={}".format(args.market_open))
    print("SUPERVISOR_NO_TICK_SKIP_AFTER={}".format(args.no_tick_skip_after))
    print_counts("SUPERVISOR_DB_START", count_rows(DEFAULT_DB_PATH))

    attempt = 0
    last_tick_count = count_rows(DEFAULT_DB_PATH).get("ticks") or 0

    while True:
        remaining = seconds_until_close(args.until)
        if remaining <= 0:
            print("SUPERVISOR_STOP_REASON=market_close_reached")
            break

        open_wait = seconds_until_time(args.market_open)
        if open_wait > 0:
            sleep_seconds = min(open_wait, remaining, args.retry_delay_sec)
            print("SUPERVISOR_WAIT_REASON=before_market_open")
            print("SUPERVISOR_WAIT_SECONDS={}".format(max(1, sleep_seconds)))
            time.sleep(max(1, sleep_seconds))
            continue

        preflight = run_preflight(
            allow_existing_python=False,
            allow_existing_kiwoom=args.allow_existing_kiwoom,
            kill_residual=False,
        )
        print_preflight_report(preflight)
        if not preflight["ok"]:
            print("SUPERVISOR_WAIT_REASON=preflight_blocked")
            time.sleep(min(args.retry_delay_sec, max(10, remaining)))
            continue

        session_seconds = max(30, remaining - 30)
        if args.attempt_seconds and args.attempt_seconds > 0:
            run_seconds = min(args.attempt_seconds, session_seconds)
        else:
            run_seconds = session_seconds

        print("SUPERVISOR_COLLECTOR_RUN_SECONDS={}".format(run_seconds))
        attempt += 1
        before = count_rows(DEFAULT_DB_PATH)
        print_counts("SUPERVISOR_DB_BEFORE_ATTEMPT_{}".format(attempt), before)

        exit_code, output = run_collector_attempt(
            attempt=attempt,
            run_seconds=run_seconds,
            login_timeout_sec=args.login_timeout_sec,
        )

        after = count_rows(DEFAULT_DB_PATH)
        print_counts("SUPERVISOR_DB_AFTER_ATTEMPT_{}".format(attempt), after)
        tick_delta = (after.get("ticks") or 0) - (before.get("ticks") or 0)
        total_delta = (after.get("ticks") or 0) - last_tick_count
        print("SUPERVISOR_ATTEMPT_DELTA={} ticks={}".format(attempt, tick_delta))
        print("SUPERVISOR_TOTAL_DELTA_FROM_LOOP_START={}".format(total_delta))

        if tick_delta > 0 and exit_code == 0:
            print("SUPERVISOR_SUCCESS=collector_saved_ticks")
            remaining = seconds_until_close(args.until)
            if remaining > 0:
                time.sleep(min(10, remaining))
            continue

        login_ok = "COLLECTOR_LOGIN_RESULT=0" in output
        realtime_registered = "COLLECTOR_REALTIME_REGISTER_RESULT=0" in output
        if (
            login_ok
            and realtime_registered
            and tick_delta <= 0
            and is_time_reached(args.no_tick_skip_after)
        ):
            print("SUPERVISOR_STOP_REASON=market_closed_or_no_ticks")
            print("SUPERVISOR_MARKET_PROBE=login_ok,realtime_registered,no_ticks")
            break

        if "COLLECTOR_LOGIN_TIMEOUT=True" in output:
            print("SUPERVISOR_FAILURE_CLASS=login_timeout")
        elif "COLLECTOR_OCX_STATUS=failed" in output:
            print("SUPERVISOR_FAILURE_CLASS=ocx_create_failed")
        else:
            print("SUPERVISOR_FAILURE_CLASS=collector_exit_{}".format(exit_code))

        remaining = seconds_until_close(args.until)
        if remaining <= 0:
            break
        time.sleep(min(args.retry_delay_sec, max(10, remaining)))

    print_counts("SUPERVISOR_DB_END", count_rows(DEFAULT_DB_PATH))
    export_shared_context(reason="intraday_supervisor_finished")
    print("SUPERVISOR_FINISHED_AT={}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
