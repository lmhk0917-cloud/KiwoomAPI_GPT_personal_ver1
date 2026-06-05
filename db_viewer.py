"""Small CLI viewer for the SQLite database."""

import argparse
import json
import sqlite3

from app_paths import DEFAULT_DB_PATH

TABLES = {
    "ticks": "received_at",
    "analysis_results": "analyzed_at",
    "event_logs": "detected_at",
    "gpt_call_logs": "started_at",
    "signal_logs": "detected_at",
    "paper_trade_results": "evaluated_at",
    "notification_logs": "sent_at",
    "historical_bars": "bar_time",
    "market_context_snapshots": "collected_at",
}


def main():
    """Parse CLI arguments and print recent rows."""
    parser = argparse.ArgumentParser(description="View Kiwoom analysis SQLite data.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--table", default="analysis_results", choices=sorted(TABLES.keys()))
    parser.add_argument("--code", help="Optional stock code filter")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Print rows as JSON")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit("DB file not found: {}".format(args.db))

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    rows = fetch_rows(conn, args.table, args.limit, args.code)

    if args.json:
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
    else:
        print_rows(rows)

    conn.close()


def fetch_rows(conn, table, limit, code=None):
    """Fetch recent rows from one whitelisted table."""
    order_col = TABLES[table]
    params = []

    where = ""
    if code and table != "gpt_call_logs":
        where = "WHERE code = ?"
        params.append(code)

    params.append(limit)

    sql = """
        SELECT *
        FROM {}
        {}
        ORDER BY {} DESC
        LIMIT ?
    """.format(table, where, order_col)

    return conn.execute(sql, params).fetchall()


def print_rows(rows):
    """Print rows in a readable key/value format."""
    if not rows:
        print("(no rows)")
        return

    columns = rows[0].keys()

    for row in rows:
        print("-" * 80)
        for column in columns:
            value = row[column]
            if isinstance(value, str) and len(value) > 200:
                value = value[:200] + "..."
            print("{}: {}".format(column, value))


if __name__ == "__main__":
    main()
