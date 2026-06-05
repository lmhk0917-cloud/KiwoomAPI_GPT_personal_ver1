"""Timed integration test for the realtime strategy app.

This runs the same RealtimeStrategyApp used by main.py, but exits after a fixed
duration so it can be used safely during market-hours debugging.
"""

import argparse
import os
import sqlite3
import sys

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
    parser.add_argument("--skip-preflight", action="store_true", help="Skip residual Kiwoom/Python session checks.")
    parser.add_argument("--allow-existing-python", action="store_true", help="Do not block on other python.exe processes.")
    parser.add_argument("--allow-existing-kiwoom", action="store_true", help="Do not block on existing Kiwoom/OpenAPI processes.")
    parser.add_argument("--kill-residual", action="store_true", help="Terminate detected project/Kiwoom residual sessions before running.")
    parser.add_argument("--preflight-only", action="store_true", help="Run only the startup preflight checks and exit.")
    parser.add_argument("--require-existing-login", action="store_true", help="Use only an already connected Kiwoom session; never call CommConnect.")
    parser.add_argument("--login-check-seconds", type=int, default=15, help="Abort early if Kiwoom is still not logged in after N seconds.")
    return parser.parse_args()


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
    before = count_rows(DEFAULT_DB_PATH)
    print_counts("DB_COUNTS_BEFORE", before)

    app = QApplication(sys.argv)
    strategy_app = RealtimeStrategyApp(require_existing_login=args.require_existing_login)

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

    def login_timeout_force_exit():
        print("TIMED_TEST_LOGIN_TIMEOUT_FORCE_EXIT=True")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(11)

    def force_exit():
        print("TIMED_TEST_FORCE_EXIT=True")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(20)

    QTimer.singleShot(duration_seconds * 1000, finish)
    QTimer.singleShot(args.login_check_seconds * 1000, login_check)
    QTimer.singleShot((duration_seconds + 30) * 1000, force_exit)
    exit_code = app.exec_()

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


if __name__ == "__main__":
    raise SystemExit(main())
