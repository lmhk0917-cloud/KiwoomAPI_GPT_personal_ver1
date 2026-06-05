"""Preview GPT input compression without calling the OpenAI API."""

import argparse
import json
import os
import sqlite3

from app_paths import DEFAULT_DB_PATH
from gpt_payload_compressor import compress_market_summaries_for_gpt


def main():
    parser = argparse.ArgumentParser(description="Preview compressed GPT payload from saved analysis rows.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--code", help="Optional stock code filter")
    parser.add_argument("--limit", type=int, default=1, help="Recent analysis rows to include")
    parser.add_argument("--show-json", action="store_true", help="Print compressed JSON payload")
    args = parser.parse_args()

    summaries = fetch_recent_summaries(args.db, code=args.code, limit=args.limit)
    compressed, stats = compress_market_summaries_for_gpt(summaries)

    print("========== GPT Payload Preview ==========")
    print("db:", args.db)
    print("code:", args.code or "(all)")
    print("rows:", len(summaries))
    print("compression_enabled:", stats.get("enabled"))
    print("original_json_chars:", stats.get("original_json_chars"))
    print("compressed_json_chars:", stats.get("compressed_json_chars"))
    print("compression_ratio:", stats.get("compression_ratio"))

    if args.show_json:
        print()
        print(json.dumps(compressed, ensure_ascii=False, indent=2, default=str))


def fetch_recent_summaries(db_path, code=None, limit=1):
    if not os.path.exists(db_path):
        raise SystemExit("DB file not found: {}".format(db_path))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        where = ""
        params = []
        if code:
            where = "WHERE code = ?"
            params.append(code)
        params.append(limit)

        rows = conn.execute("""
            SELECT summary_json
            FROM analysis_results
            {}
            ORDER BY analyzed_at DESC
            LIMIT ?
        """.format(where), params).fetchall()
    finally:
        conn.close()

    summaries = []
    for row in rows:
        if not row["summary_json"]:
            continue
        try:
            summaries.append(json.loads(row["summary_json"]))
        except (TypeError, ValueError):
            continue

    return summaries


if __name__ == "__main__":
    main()
