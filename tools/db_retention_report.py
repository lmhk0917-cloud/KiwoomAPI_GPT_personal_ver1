"""Report SQLite storage size and retention candidates without deleting data."""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app_paths import DEFAULT_DB_PATH


TABLE_TIME_COLUMNS = {
    "ticks": "received_at",
    "historical_bars": "bar_time",
    "analysis_results": "analyzed_at",
    "event_logs": "detected_at",
    "gpt_call_logs": "started_at",
    "signal_logs": "detected_at",
    "paper_trade_results": "evaluated_at",
    "market_context_snapshots": "collected_at",
}


def main():
    parser = argparse.ArgumentParser(description="Show DB storage and retention candidates. No writes are performed.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--hot-days", type=int, default=120, help="Keep this many recent days in the hot DB.")
    args = parser.parse_args()

    report(args.db, hot_days=args.hot_days)


def report(db_path, hot_days=120):
    if not os.path.exists(db_path):
        raise RuntimeError("DB not found: {}".format(db_path))
    cutoff = (datetime.now() - timedelta(days=int(hot_days))).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        print("DB_RETENTION_REPORT")
        print("db_path={}".format(db_path))
        print("db_size_mb={:.2f}".format(os.path.getsize(db_path) / 1024.0 / 1024.0))
        print("hot_days={}".format(hot_days))
        print("archive_before={}".format(cutoff))
        for table, time_col in TABLE_TIME_COLUMNS.items():
            if not has_table(conn, table):
                continue
            total = scalar(conn, "SELECT COUNT(1) FROM {}".format(table))
            oldest = scalar(conn, "SELECT MIN({}) FROM {}".format(time_col, table))
            latest = scalar(conn, "SELECT MAX({}) FROM {}".format(time_col, table))
            archive_candidates = scalar(
                conn,
                "SELECT COUNT(1) FROM {} WHERE {} < ?".format(table, time_col),
                (cutoff,),
            )
            print(
                "table={table} rows={rows} oldest={oldest} latest={latest} archive_candidates={archive}".format(
                    table=table,
                    rows=total,
                    oldest=oldest or "-",
                    latest=latest or "-",
                    archive=archive_candidates,
                )
            )
        print("mode=dry_run")
        print("note=No rows were moved or deleted.")
    finally:
        conn.close()


def has_table(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def scalar(conn, query, params=()):
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


if __name__ == "__main__":
    main()
