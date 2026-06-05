"""Quality checks for historical_bars backfill data."""

import argparse
import sqlite3

from app_paths import DEFAULT_DB_PATH
from config import WATCH_CODES
from data_store import TickStore

TIMEFRAMES = ["day", "1m", "3m", "5m"]


def parse_args():
    parser = argparse.ArgumentParser(description="Check historical_bars quality.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--codes", default=None, help="Comma-separated codes. Defaults to WATCH_CODES.")
    return parser.parse_args()


def parse_codes(raw_codes):
    if raw_codes:
        return [code.strip() for code in raw_codes.split(",") if code.strip()]
    return list(WATCH_CODES.keys())


def fetch_one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def check_code_timeframe(conn, code, timeframe):
    row = conn.execute("""
        SELECT
            COUNT(1) AS count,
            MIN(bar_time) AS oldest_bar_time,
            MAX(bar_time) AS latest_bar_time,
            SUM(CASE WHEN close IS NULL OR open IS NULL OR high IS NULL OR low IS NULL THEN 1 ELSE 0 END) AS null_ohlc,
            SUM(CASE WHEN volume IS NULL THEN 1 ELSE 0 END) AS null_volume,
            SUM(CASE WHEN high < low THEN 1 ELSE 0 END) AS high_low_bad,
            SUM(CASE WHEN high < open OR high < close OR low > open OR low > close THEN 1 ELSE 0 END) AS ohlc_range_bad,
            SUM(CASE WHEN close <= 0 OR open <= 0 OR high <= 0 OR low <= 0 THEN 1 ELSE 0 END) AS nonpositive_ohlc,
            SUM(CASE WHEN volume < 0 THEN 1 ELSE 0 END) AS negative_volume
        FROM historical_bars
        WHERE code = ?
          AND timeframe = ?
    """, (code, timeframe)).fetchone()

    duplicates = fetch_one(conn, """
        SELECT COUNT(1)
        FROM (
            SELECT bar_time, COUNT(1) AS cnt
            FROM historical_bars
            WHERE code = ?
              AND timeframe = ?
            GROUP BY bar_time
            HAVING cnt > 1
        )
    """, (code, timeframe))

    latest_close = conn.execute("""
        SELECT close
        FROM historical_bars
        WHERE code = ?
          AND timeframe = ?
        ORDER BY bar_time DESC
        LIMIT 1
    """, (code, timeframe)).fetchone()

    latest_tick = conn.execute("""
        SELECT price, received_at
        FROM ticks
        WHERE code = ?
        ORDER BY id DESC
        LIMIT 1
    """, (code,)).fetchone()

    latest_close_value = latest_close[0] if latest_close else None
    latest_tick_price = latest_tick["price"] if latest_tick else None
    latest_tick_time = latest_tick["received_at"] if latest_tick else None
    tick_gap_pct = pct_gap(latest_close_value, latest_tick_price)

    problems = []
    for key in (
        "null_ohlc",
        "high_low_bad",
        "ohlc_range_bad",
        "nonpositive_ohlc",
        "negative_volume",
    ):
        if row[key]:
            problems.append("{}={}".format(key, row[key]))

    if duplicates:
        problems.append("duplicates={}".format(duplicates))

    return {
        "count": row["count"],
        "oldest_bar_time": row["oldest_bar_time"],
        "latest_bar_time": row["latest_bar_time"],
        "null_volume": row["null_volume"],
        "latest_close": latest_close_value,
        "latest_tick_price": latest_tick_price,
        "latest_tick_time": latest_tick_time,
        "tick_gap_pct": tick_gap_pct,
        "problems": problems,
    }


def pct_gap(left, right):
    try:
        if left is None or right is None or float(right) == 0:
            return None
        return round((float(left) - float(right)) / float(right) * 100.0, 3)
    except (TypeError, ValueError):
        return None


def print_summary(conn, codes):
    total = fetch_one(conn, "SELECT COUNT(1) FROM historical_bars")
    duplicate_groups = fetch_one(conn, """
        SELECT COUNT(1)
        FROM (
            SELECT code, timeframe, bar_time, COUNT(1) AS cnt
            FROM historical_bars
            GROUP BY code, timeframe, bar_time
            HAVING cnt > 1
        )
    """)

    print("TOTAL_HISTORICAL_BARS={}".format(total))
    print("DUPLICATE_GROUPS={}".format(duplicate_groups))

    for code in codes:
        print("CODE={}".format(code))
        for timeframe in TIMEFRAMES:
            result = check_code_timeframe(conn, code, timeframe)
            print(
                "  {tf} count={count} oldest={oldest} latest={latest} "
                "latest_close={close} tick_gap_pct={gap} null_volume={null_volume} problems={problems}"
                .format(
                    tf=timeframe,
                    count=result["count"],
                    oldest=result["oldest_bar_time"],
                    latest=result["latest_bar_time"],
                    close=result["latest_close"],
                    gap=result["tick_gap_pct"],
                    null_volume=result["null_volume"],
                    problems="none" if not result["problems"] else ";".join(result["problems"]),
                )
            )


def print_gpt_context_check(codes):
    store = TickStore()
    try:
        for code in codes:
            ctx = store.get_historical_price_context(code)
            print("GPT_CONTEXT_CODE={}".format(code))
            for key in ("daily", "minute_1m", "minute_3m", "minute_5m"):
                value = ctx.get(key) or {}
                print(
                    "  {key} sample={sample} latest={latest} r1={r1} r20={r20} vol20={vol20} note={note}"
                    .format(
                        key=key,
                        sample=value.get("sample_size"),
                        latest=value.get("latest_close"),
                        r1=value.get("return_1bar_pct"),
                        r20=value.get("return_20bar_pct"),
                        vol20=value.get("volume_ratio_20bar"),
                        note=value.get("note"),
                    )
                )
    finally:
        store.close()


def main():
    args = parse_args()
    codes = parse_codes(args.codes)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    try:
        print_summary(conn, codes)
    finally:
        conn.close()

    print_gpt_context_check(codes)


if __name__ == "__main__":
    main()
