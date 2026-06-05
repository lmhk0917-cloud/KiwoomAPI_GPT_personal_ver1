"""Summarize stored market-context snapshots."""

import argparse
import json
import os
import sqlite3

from app_paths import DEFAULT_DB_PATH


def main():
    parser = argparse.ArgumentParser(description="View stored Kiwoom/manual market context snapshots.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--code", help="Optional stock code filter")
    parser.add_argument("--section", help="Optional context section filter")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="Print full rows as JSON")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit("DB file not found: {}".format(args.db))

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = fetch_rows(conn, args.code, args.section, args.limit)
    finally:
        conn.close()

    if args.json:
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
    else:
        print_rows(rows)


def fetch_rows(conn, code=None, section=None, limit=20):
    where = []
    params = []

    if code:
        where.append("code = ?")
        params.append(code)

    if section:
        where.append("section = ?")
        params.append(section)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    params.append(limit)

    return conn.execute("""
        SELECT
            id, collected_at, scope, code, section, source, asof,
            reliability, weight, summary, payload_json
        FROM market_context_snapshots
        {}
        ORDER BY collected_at DESC
        LIMIT ?
    """.format(where_sql), params).fetchall()


def print_rows(rows):
    if not rows:
        print("(no market context snapshots)")
        return

    for row in rows:
        payload_text = row["payload_json"] or ""
        if len(payload_text) > 300:
            payload_text = payload_text[:300] + "..."

        label_code = row["code"] if row["code"] else "GLOBAL"
        print("-" * 80)
        print("id: {}".format(row["id"]))
        print("collected_at: {}".format(row["collected_at"]))
        print("scope/code: {}/{}".format(row["scope"], label_code))
        print("section/source: {}/{}".format(row["section"], row["source"]))
        print("asof: {}".format(row["asof"]))
        print("reliability/weight: {}/{}".format(row["reliability"], row["weight"]))
        print("summary: {}".format(row["summary"]))
        print("payload_json: {}".format(payload_text))


if __name__ == "__main__":
    main()
