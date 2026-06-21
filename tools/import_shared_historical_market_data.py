"""Import shared daily historical market data without creating synthetic ticks."""

import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app_paths import DEFAULT_DB_PATH
from data_store import TickStore


DEFAULT_PACKAGE = (
    r"C:\Users\lmhk2\Documents\New project\market_data_exports\daily_history"
    r"\yahoo_finance_10y_ai_semiconductor_1d\shared"
    r"\historical_market_data_v1_daily_kr_us_ai_semiconductor.json"
)


def main():
    parser = argparse.ArgumentParser(description="Import shared daily historical bars into Kiwoom SQLite.")
    parser.add_argument("--file", default=DEFAULT_PACKAGE)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--markets", default="KRX")
    parser.add_argument("--merge-context", action="store_true")
    args = parser.parse_args()

    package = load_package(args.file)
    validate_daily_package(package)
    markets = set(item.strip().upper() for item in args.markets.split(",") if item.strip())
    bars = build_historical_bars(package, markets=markets)
    store = TickStore(db_path=args.db)
    try:
        saved_bars = store.save_historical_bars(bars)
        saved_context = save_context_snapshots(store, package, bars) if args.merge_context else 0
    finally:
        store.close()

    print("SHARED_HISTORICAL_IMPORT_STATUS=ok")
    print("SHARED_HISTORICAL_IMPORT_FILE={}".format(args.file))
    print("SHARED_HISTORICAL_IMPORT_DB={}".format(args.db))
    print("SHARED_HISTORICAL_IMPORT_TIMEFRAME=day")
    print("SHARED_HISTORICAL_IMPORT_TICKS_CREATED=0")
    print("SHARED_HISTORICAL_IMPORT_BARS={}".format(saved_bars))
    print("SHARED_HISTORICAL_IMPORT_CONTEXT={}".format(saved_context))


def load_package(path):
    if not os.path.exists(path):
        raise RuntimeError("Shared historical package not found: {}".format(path))
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def validate_daily_package(package):
    if package.get("schema") != "historical_market_data_v1":
        raise RuntimeError("Unsupported package schema: {}".format(package.get("schema")))
    resolution = package.get("resolution") or {}
    if resolution.get("timeframe") != "1d":
        raise RuntimeError("Only daily shared history is supported; got {}".format(resolution.get("timeframe")))
    if resolution.get("intraday_source") or resolution.get("tick_source"):
        raise RuntimeError("Refusing to import package that claims intraday/tick source.")


def build_historical_bars(package, markets):
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    rows = []
    for item in package.get("bars") or []:
        if str(item.get("market") or "").upper() not in markets:
            continue
        rows.append({
            "code": str(item.get("code") or ""),
            "timeframe": "day",
            "bar_time": item.get("bar_time") or "{} 00:00:00".format(item.get("date")),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": item.get("close"),
            "volume": int(item.get("volume") or 0),
            "trading_value": None,
            "source": "shared_yahoo_history_daily",
            "fetched_at": fetched_at,
        })
    return rows


def save_context_snapshots(store, package, bars):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    saved = 0
    by_code = {}
    for bar in bars:
        by_code.setdefault(bar["code"], 0)
        by_code[bar["code"]] += 1
    for code, count in sorted(by_code.items()):
        store.save_market_context_snapshot(
            scope="code",
            code=code,
            section="external_daily_history",
            payload={
                "source": "shared_yahoo_history_daily",
                "asof": package.get("generated_at"),
                "reliability": "reference",
                "weight": "low_for_intraday",
                "summary": "Daily historical OHLCV imported for long-horizon context only.",
                "timeframe": "day",
                "bar_count": count,
                "intraday_source": False,
                "tick_source": False,
                "warning": (package.get("resolution") or {}).get("warning"),
            },
            collected_at=now,
        )
        saved += 1
    return saved


if __name__ == "__main__":
    main()
