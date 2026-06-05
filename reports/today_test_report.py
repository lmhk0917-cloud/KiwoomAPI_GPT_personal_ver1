"""Print a compact report for one intraday test date."""

import argparse
import os
import sqlite3
from datetime import datetime

from app_paths import DEFAULT_DB_PATH


TABLE_DATE_COLUMNS = [
    ("ticks", "received_at"),
    ("analysis_results", "analyzed_at"),
    ("event_logs", "detected_at"),
    ("gpt_call_logs", "started_at"),
    ("signal_logs", "detected_at"),
    ("notification_logs", "sent_at"),
    ("paper_trade_results", "evaluated_at"),
    ("market_context_snapshots", "collected_at"),
]


def main():
    parser = argparse.ArgumentParser(description="Show daily Kiwoom/GPT test report.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    try:
        print("REPORT_DATE", args.date)
        print("DB_SIZE_MB", round(os.path.getsize(args.db) / 1024 / 1024, 2))
        print_counts(conn, args.date)
        print_ticks_by_code(conn, args.date)
        print_gpt(conn, args.date)
        print_signals(conn, args.date)
        print_notifications(conn, args.date)
        print_paper_summary(conn, args.date)
    finally:
        conn.close()


def print_counts(conn, date_text):
    print("COUNTS")
    for table, column in TABLE_DATE_COLUMNS:
        try:
            count = conn.execute(
                "SELECT COUNT(1) FROM {} WHERE {} LIKE ?".format(table, column),
                (date_text + "%",),
            ).fetchone()[0]
            print(table, count)
        except sqlite3.Error as exc:
            print(table, "ERR", exc)


def print_ticks_by_code(conn, date_text):
    print("TICKS_BY_CODE")
    rows = conn.execute("""
        SELECT code,
               COUNT(1) AS tick_count,
               MIN(received_at) AS first_at,
               MAX(received_at) AS last_at
        FROM ticks
        WHERE received_at LIKE ?
        GROUP BY code
        ORDER BY code
    """, (date_text + "%",)).fetchall()
    for row in rows:
        print(dict(row))


def print_gpt(conn, date_text):
    print("GPT_OVERVIEW")
    row = conn.execute("""
        SELECT COUNT(1) AS calls,
               SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
               SUM(prompt_tokens) AS prompt_tokens,
               SUM(completion_tokens) AS completion_tokens,
               SUM(total_tokens) AS total_tokens,
               ROUND(AVG(duration_ms), 1) AS avg_ms
        FROM gpt_call_logs
        WHERE started_at LIKE ?
    """, (date_text + "%",)).fetchone()
    print(dict(row))

    print("GPT_BY_CODES")
    rows = conn.execute("""
        SELECT codes,
               COUNT(1) AS calls,
               SUM(total_tokens) AS tokens
        FROM gpt_call_logs
        WHERE started_at LIKE ?
        GROUP BY codes
        ORDER BY calls DESC
    """, (date_text + "%",)).fetchall()
    for row in rows:
        print(dict(row))


def print_signals(conn, date_text):
    print("SIGNALS_BY_ACTION")
    rows = conn.execute("""
        SELECT action_hint,
               COUNT(1) AS count,
               ROUND(AVG(confidence_score), 2) AS avg_score
        FROM signal_logs
        WHERE detected_at LIKE ?
        GROUP BY action_hint
        ORDER BY count DESC
    """, (date_text + "%",)).fetchall()
    for row in rows:
        print(dict(row))


def print_notifications(conn, date_text):
    print("NOTIFICATIONS")
    rows = conn.execute("""
        SELECT channel,
               status,
               COUNT(1) AS count
        FROM notification_logs
        WHERE sent_at LIKE ?
        GROUP BY channel, status
        ORDER BY channel, status
    """, (date_text + "%",)).fetchall()
    for row in rows:
        print(dict(row))


def print_paper_summary(conn, date_text):
    print("PAPER_TRADE_TODAY_SIGNALS")
    row = conn.execute("""
        SELECT COUNT(1) AS evaluated,
               ROUND(AVG(r.return_5m_pct), 3) AS avg_5m,
               ROUND(AVG(r.return_10m_pct), 3) AS avg_10m,
               ROUND(AVG(r.return_30m_pct), 3) AS avg_30m,
               ROUND(AVG(r.return_60m_pct), 3) AS avg_60m,
               ROUND(AVG(CASE WHEN r.return_60m_pct > 0 THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_60m,
               ROUND(AVG(CASE WHEN r.stop_loss_hit = 1 THEN 1.0 ELSE 0.0 END) * 100, 2) AS stop_rate
        FROM signal_logs s
        JOIN paper_trade_results r
          ON r.signal_id = s.id
        WHERE s.detected_at LIKE ?
    """, (date_text + "%",)).fetchone()
    print(dict(row))

    print("PAPER_BY_ACTION")
    rows = conn.execute("""
        SELECT s.action_hint,
               COUNT(1) AS evaluated,
               ROUND(AVG(r.return_30m_pct), 3) AS avg_30m,
               ROUND(AVG(r.return_60m_pct), 3) AS avg_60m,
               ROUND(AVG(CASE WHEN r.return_60m_pct > 0 THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_60m,
               ROUND(AVG(CASE WHEN r.stop_loss_hit = 1 THEN 1.0 ELSE 0.0 END) * 100, 2) AS stop_rate
        FROM signal_logs s
        JOIN paper_trade_results r
          ON r.signal_id = s.id
        WHERE s.detected_at LIKE ?
        GROUP BY s.action_hint
        ORDER BY evaluated DESC, avg_60m DESC
    """, (date_text + "%",)).fetchall()
    for row in rows:
        print(dict(row))


if __name__ == "__main__":
    main()
