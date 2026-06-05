"""Update manual market-wide status context for GPT analysis.

Use this when a sidecar, circuit breaker, VI state, or other broad market state
must be reflected immediately before automatic Kiwoom mappings are verified.
"""

import argparse
import json
import os
from datetime import datetime

from app_paths import DEFAULT_DB_PATH, PROJECT_DIR
from data_store import TickStore


DEFAULT_PATH = os.path.join(PROJECT_DIR, "market_context.json")


def parse_args():
    parser = argparse.ArgumentParser(description="Update market_context.json market_status.")
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--market", default="KOSPI")
    parser.add_argument("--phase", default="regular")
    parser.add_argument("--sidecar-status", default="inactive", choices=["inactive", "active", "triggered", "ended"])
    parser.add_argument("--sidecar-direction", default=None, choices=["buy", "sell", "unknown"])
    parser.add_argument("--sidecar-started-at", default=None)
    parser.add_argument("--sidecar-ended-at", default=None)
    parser.add_argument("--circuit-breaker-status", default="inactive", choices=["inactive", "active", "triggered", "ended"])
    parser.add_argument("--vi-status", default="inactive", choices=["inactive", "active", "triggered", "ended"])
    parser.add_argument("--summary", default=None)
    parser.add_argument("--source", default="manual")
    parser.add_argument("--reliability", default="manual_or_unverified")
    parser.add_argument("--sell-sidecar", action="store_true", help="Shortcut for a triggered KOSPI sell sidecar.")
    parser.add_argument("--buy-sidecar", action="store_true", help="Shortcut for a triggered KOSPI buy sidecar.")
    parser.add_argument("--ended", action="store_true", help="Mark the current sidecar as ended.")
    parser.add_argument("--save-db", action="store_true", help="Also save a market_status snapshot into SQLite.")
    return parser.parse_args()


def load_context(path):
    if not os.path.exists(path):
        return {"global": {}, "codes": {}}

    with open(path, "r", encoding="utf-8-sig") as fp:
        return json.load(fp)


def save_context(path, data):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def main():
    args = parse_args()
    apply_shortcuts(args)
    data = load_context(args.path)
    data.setdefault("global", {})
    data.setdefault("codes", {})

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["global"]["asof"] = now_text
    data["global"]["market_status"] = {
        "asof": now_text,
        "market": args.market,
        "sidecar_status": args.sidecar_status,
        "sidecar_direction": args.sidecar_direction,
        "sidecar_started_at": args.sidecar_started_at,
        "sidecar_ended_at": args.sidecar_ended_at,
        "circuit_breaker_status": args.circuit_breaker_status,
        "vi_status": args.vi_status,
        "market_phase": args.phase,
        "summary": args.summary or build_default_summary(args),
        "source": args.source,
        "reliability": args.reliability,
    }

    save_context(args.path, data)

    if args.save_db:
        save_market_status_snapshot(args.db, data["global"]["market_status"])

    print("market_context_updated=True")
    print("path={}".format(args.path))
    print("sidecar_status={}".format(args.sidecar_status))
    print("circuit_breaker_status={}".format(args.circuit_breaker_status))
    print("vi_status={}".format(args.vi_status))
    if args.save_db:
        print("saved_market_status_snapshot=True")


def apply_shortcuts(args):
    """Apply convenience flags without hiding the explicit CLI fields."""
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if args.sell_sidecar:
        args.sidecar_status = "triggered"
        args.sidecar_direction = "sell"
        args.sidecar_started_at = args.sidecar_started_at or now_text
        args.source = args.source or "manual"

    if args.buy_sidecar:
        args.sidecar_status = "triggered"
        args.sidecar_direction = "buy"
        args.sidecar_started_at = args.sidecar_started_at or now_text
        args.source = args.source or "manual"

    if args.ended:
        args.sidecar_status = "ended"
        args.sidecar_ended_at = args.sidecar_ended_at or now_text


def save_market_status_snapshot(db_path, market_status):
    store = TickStore(db_path=db_path)
    try:
        store.save_market_context_snapshot(
            scope="global",
            section="market_status",
            payload=market_status,
            collected_at=market_status.get("asof"),
            source=market_status.get("source"),
            reliability=market_status.get("reliability"),
            summary=market_status.get("summary"),
        )
    finally:
        store.close()


def build_default_summary(args):
    if args.sidecar_status in ("active", "triggered"):
        return "{} {} sidecar is {}.".format(
            args.market,
            args.sidecar_direction or "unknown",
            args.sidecar_status,
        )
    if args.circuit_breaker_status in ("active", "triggered"):
        return "{} circuit breaker is {}.".format(args.market, args.circuit_breaker_status)
    if args.vi_status in ("active", "triggered"):
        return "{} VI state is {}.".format(args.market, args.vi_status)
    if args.sidecar_status == "ended":
        return "{} sidecar has ended.".format(args.market)
    return "No abnormal market-wide interruption state is currently recorded."


if __name__ == "__main__":
    main()
