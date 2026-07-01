"""Timed integration test for the realtime strategy app.

This runs the same RealtimeStrategyApp used by main.py, but exits after a fixed
duration so it can be used safely during market-hours debugging.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from app_paths import DEFAULT_DB_PATH, setup_runtime_logging
from main import RealtimeStrategyApp
from preflight_check import print_preflight_report, run_preflight


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
    """Return row counts for the tables touched by the realtime app."""
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
    finally:
        conn.close()

    return counts


def print_counts(label, counts):
    print("{}={}".format(label, ",".join(
        "{}:{}".format(key, counts.get(key)) for key in TABLES
    )))


def parse_args():
    parser = argparse.ArgumentParser(description="Run main.py flow for a fixed duration.")
    parser.add_argument("--seconds", type=int, default=130)
    parser.add_argument("--minutes", type=int, help="Run duration in minutes. Overrides --seconds.")
    parser.add_argument("--paper-report", action="store_true", help="Print paper-trade report after the run.")
    parser.add_argument("--paper-report-min-sample", type=int, default=5)
    parser.add_argument("--skip-final-paper-evaluation", action="store_true", help="Skip post-run pending paper-trade evaluation before reporting.")
    parser.add_argument("--final-paper-evaluate-limit", type=int, default=1000, help="Maximum same-day pending signals to evaluate after the timed run.")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip residual Kiwoom/Python session checks.")
    parser.add_argument("--allow-existing-python", action="store_true", help="Do not block on other python.exe processes.")
    parser.add_argument("--allow-existing-kiwoom", action="store_true", help="Do not block on existing Kiwoom/OpenAPI processes.")
    parser.add_argument("--kill-residual", action="store_true", help="Terminate detected project/Kiwoom residual sessions before running.")
    parser.add_argument("--preflight-only", action="store_true", help="Run only the startup preflight checks and exit.")
    parser.add_argument("--require-existing-login", action="store_true", help="Use only an already connected Kiwoom session; never call CommConnect.")
    parser.add_argument("--login-check-seconds", type=int, default=15, help="Abort early if Kiwoom is still not logged in after N seconds.")
    parser.add_argument("--tick-watchdog-after", type=valid_hhmm, default="09:02", help="Abort if no new ticks arrive after this local HH:MM.")
    parser.add_argument("--tick-watchdog-grace-sec", type=int, default=180, help="Seconds to wait after --tick-watchdog-after before aborting on zero tick delta.")
    parser.add_argument("--disable-tick-watchdog", action="store_true", help="Disable the post-open no-tick abort watchdog.")
    return parser.parse_args()


def valid_hhmm(value):
    try:
        hour, minute = [int(part) for part in str(value).split(":", 1)]
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("expected HH:MM")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise argparse.ArgumentTypeError("expected HH:MM in 00:00-23:59")
    return "{:02d}:{:02d}".format(hour, minute)


def today_at_hhmm(value):
    hour, minute = [int(part) for part in valid_hhmm(value).split(":", 1)]
    return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)


def tick_watchdog_deadline_timestamp(watchdog_after, grace_sec, process_started_at=None):
    """Return the no-tick watchdog deadline for this process run."""
    process_started_at = process_started_at or datetime.now()
    grace_sec = max(0, int(grace_sec))
    market_open_deadline = today_at_hhmm(watchdog_after).timestamp() + grace_sec
    process_start_deadline = process_started_at.timestamp() + grace_sec
    return max(market_open_deadline, process_start_deadline)


def main():
    args = parse_args()
    setup_runtime_logging("main_timed_test")

    if not args.skip_preflight:
        preflight_result = run_preflight(
            allow_existing_python=args.allow_existing_python,
            allow_existing_kiwoom=args.allow_existing_kiwoom,
            kill_residual=args.kill_residual,
        )
        print_preflight_report(preflight_result)

        if not preflight_result["ok"]:
            print("TIMED_TEST_ABORTED=preflight_failed")
            return 10

    if args.preflight_only:
        print("TIMED_TEST_ABORTED=preflight_only")
        return 0

    duration_seconds = args.minutes * 60 if args.minutes is not None else args.seconds
    process_started_at = datetime.now()
    before = count_rows(DEFAULT_DB_PATH)
    print_counts("DB_COUNTS_BEFORE", before)
    tick_watchdog_deadline = tick_watchdog_deadline_timestamp(
        args.tick_watchdog_after,
        args.tick_watchdog_grace_sec,
        process_started_at=process_started_at,
    )

    app = QApplication(sys.argv)
    strategy_app = RealtimeStrategyApp(require_existing_login=args.require_existing_login)
    finish_requested = {"value": False}

    def login_check():
        if strategy_app.kiwoom.is_logged_in:
            print("LOGIN_CHECK_STATUS=logged_in")
            return
        print("LOGIN_CHECK_STATUS=not_logged_in")
        abort_reason = (
            "existing_login_not_confirmed"
            if args.require_existing_login
            else "login_not_confirmed"
        )
        print("TIMED_TEST_ABORTED={}".format(abort_reason))
        QTimer.singleShot(5000, login_timeout_force_exit)
        finish(exit_code=11)

    def finish(exit_code=0):
        if finish_requested["value"]:
            return
        finish_requested["value"] = True
        print("TIMED_TEST_FINISH_REQUESTED=True")
        try:
            strategy_app.timer.stop()
        except Exception as exc:
            print("ANALYSIS_TIMER_STOP_ERROR={}".format(exc))
        if strategy_app.kiwoom.is_logged_in:
            try:
                strategy_app.kiwoom.clear_realtime_codes()
            except Exception as exc:
                print("REALTIME_CLEAR_ERROR={}".format(exc))
        else:
            print("REALTIME_CLEAR_SKIPPED=not_logged_in")
        try:
            strategy_app.tick_store.close()
        except Exception as exc:
            print("DB_CLOSE_ERROR={}".format(exc))
        QApplication.instance().exit(exit_code)

    def health_watchdog():
        if finish_requested["value"]:
            return

        if strategy_app.kiwoom.ever_logged_in and not strategy_app.kiwoom.is_logged_in:
            print("TIMED_TEST_ABORTED=login_lost")
            print("LOGIN_LOST_ERROR_CODE={}".format(strategy_app.kiwoom.last_login_error_code))
            QTimer.singleShot(5000, login_lost_force_exit)
            finish(exit_code=12)
            return

        if not args.disable_tick_watchdog and datetime.now().timestamp() >= tick_watchdog_deadline:
            if not strategy_app.kiwoom.is_logged_in:
                print("TICK_WATCHDOG_SKIPPED=not_logged_in")
                QTimer.singleShot(30000, health_watchdog)
                return

            current = count_rows(DEFAULT_DB_PATH)
            tick_delta = (
                None
                if before.get("ticks") is None or current.get("ticks") is None
                else current.get("ticks") - before.get("ticks")
            )
            if tick_delta == 0:
                print("TIMED_TEST_ABORTED=no_tick_after_open")
                print("TICK_WATCHDOG_AFTER={}".format(args.tick_watchdog_after))
                print("TICK_WATCHDOG_GRACE_SEC={}".format(args.tick_watchdog_grace_sec))
                print("TICK_WATCHDOG_DELTA=0")
                QTimer.singleShot(5000, no_tick_force_exit)
                finish(exit_code=13)
                return

        QTimer.singleShot(30000, health_watchdog)

    def login_timeout_force_exit():
        print("TIMED_TEST_LOGIN_TIMEOUT_FORCE_EXIT=True")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(11)

    def login_lost_force_exit():
        print("TIMED_TEST_LOGIN_LOST_FORCE_EXIT=True")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(12)

    def no_tick_force_exit():
        print("TIMED_TEST_NO_TICK_FORCE_EXIT=True")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(13)

    def force_exit():
        print("TIMED_TEST_FORCE_EXIT=True")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(20)

    QTimer.singleShot(duration_seconds * 1000, finish)
    QTimer.singleShot(args.login_check_seconds * 1000, login_check)
    QTimer.singleShot(30000, health_watchdog)
    QTimer.singleShot((duration_seconds + 30) * 1000, force_exit)
    exit_code = app.exec_()

    if args.paper_report and not args.skip_final_paper_evaluation:
        evaluate_final_paper_trades(args.final_paper_evaluate_limit)

    after = count_rows(DEFAULT_DB_PATH)
    print_counts("DB_COUNTS_AFTER", after)
    print_counts("DB_COUNTS_DELTA", {
        key: (
            None
            if before.get(key) is None or after.get(key) is None
            else after.get(key) - before.get(key)
        )
        for key in TABLES
    })

    if args.paper_report:
        print_paper_report(args.paper_report_min_sample)

    return exit_code


def print_paper_report(min_sample):
    """Print the paper-trade quality summary after a timed market test."""
    from data_store import TickStore
    from paper_trade_report import build_report, print_text_report

    store = TickStore(db_path=DEFAULT_DB_PATH)
    try:
        report = build_report(
            conn=store.conn,
            min_sample=min_sample,
            recent_limit=10,
        )
        print_text_report(report)
    finally:
        store.close()


def evaluate_final_paper_trades(limit):
    """Evaluate same-day pending paper rows before printing the final report."""
    from data_store import TickStore
    from quant_feedback import evaluate_pending, save_feedback_snapshots

    since = "{} 00:00:00".format(datetime.now().strftime("%Y-%m-%d"))
    store = TickStore(db_path=DEFAULT_DB_PATH)
    try:
        evaluated = evaluate_pending(
            store=store,
            since=since,
            limit=max(0, int(limit)),
            allow_partial=True,
        )
        print("FINAL_PAPER_EVALUATED={}".format(evaluated))
        if evaluated:
            snapshots = save_feedback_snapshots(
                store=store,
                days=1,
                min_sample=3,
            )
            print("FINAL_QUANT_FEEDBACK_SNAPSHOTS={}".format(len(snapshots)))
    except Exception as exc:
        print("FINAL_PAPER_EVALUATION_ERROR={}".format(exc))
        raise
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
