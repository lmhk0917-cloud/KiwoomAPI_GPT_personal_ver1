"""Inspect saved realtime ticks and event conditions without calling GPT."""

import argparse
import sqlite3

from app_paths import DEFAULT_DB_PATH
from config import WATCH_CODES
from event_detector import detect_gpt_events
from indicators import summarize_multi_timeframes_for_gpt
from settings_store import SettingsStore


def parse_args():
    parser = argparse.ArgumentParser(description="Inspect recent live ticks.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=5000)
    return parser.parse_args()


def load_watch_codes(db_path):
    try:
        settings = SettingsStore(db_path=db_path)
        watch_codes = settings.get("WATCH_CODES", WATCH_CODES)
        settings.close()
        return watch_codes
    except Exception:
        return WATCH_CODES


def fetch_ticks(conn, code, limit):
    rows = conn.execute("""
        SELECT
            code, trade_time, price, change_rate, acc_volume, tick_volume,
            open_price, high_price, low_price, strength, received_at
        FROM ticks
        WHERE code = ?
        ORDER BY id DESC
        LIMIT ?
    """, (code, limit)).fetchall()

    ticks = []
    for row in reversed(rows):
        ticks.append({key: row[key] for key in row.keys()})
    return ticks


def compact_timeframe(tf_summary):
    if not tf_summary:
        return "none"

    latest = tf_summary.get("latest", {})
    momentum = tf_summary.get("momentum", {})
    volume = tf_summary.get("volume", {})
    box_range = tf_summary.get("box_range") or {}
    vwap = tf_summary.get("vwap") or {}
    return (
        "bars={bars} close={close} rsi={rsi} vol20={vol} "
        "box={box} vwap={vwap}"
    ).format(
        bars=tf_summary.get("bar_count"),
        close=latest.get("close"),
        rsi=momentum.get("rsi14"),
        vol=volume.get("volume_ratio_20"),
        box=box_range.get("current_position_in_box"),
        vwap=vwap.get("vwap_distance_pct"),
    )


def main():
    args = parse_args()
    watch_codes = load_watch_codes(args.db)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    try:
        for code, name in watch_codes.items():
            ticks = fetch_ticks(conn, code, args.limit)
            print("SYMBOL={} {} TICKS={}".format(code, name, len(ticks)))

            if not ticks:
                continue

            summary = summarize_multi_timeframes_for_gpt(
                code=code,
                name=name,
                ticks=ticks,
                drop_last=True,
            )

            if not summary:
                print("  SUMMARY=none")
                continue

            events = detect_gpt_events(summary)
            print("  EVENTS={}".format([event.get("type") for event in events]))

            timeframes = summary.get("timeframes") or {}
            for timeframe in ("1m", "3m", "5m"):
                print("  {} {}".format(
                    timeframe,
                    compact_timeframe(timeframes.get(timeframe))
                ))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
