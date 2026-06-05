"""Offline end-to-end simulation for debugging without Kiwoom login.

This script generates deterministic fake ticks, runs the same indicator/event/
signal/database path as the realtime app, and optionally sends notifications.
It is the safest way to validate changes outside regular market hours.
"""

import argparse
import os
from datetime import datetime, timedelta

from app_paths import DATA_DIR, ensure_app_dirs
from config import GPT_COOLDOWN_SEC
from data_store import TickStore
from event_detector import detect_gpt_events
from indicators import summarize_multi_timeframes_for_gpt
from notifier import Notifier
from paper_trade_simulator import evaluate_signal, fetch_pending_signals, parse_dt
from signal_generator import generate_validation_signal


DEFAULT_DB_PATH = os.path.join(DATA_DIR, "simulation_debug.db")


def main():
    """CLI entrypoint for simulation runs."""
    ensure_app_dirs()
    parser = argparse.ArgumentParser(description="Run an offline end-to-end simulation.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--reset", action="store_true", help="Delete the simulation DB before running")
    parser.add_argument("--count", type=int, default=720, help="Ticks per scenario")
    parser.add_argument("--cycle-ticks", type=int, default=30, help="Analyze every N ticks")
    parser.add_argument("--notify", action="store_true", help="Send configured notifications during simulation")
    args = parser.parse_args()

    if args.reset and os.path.exists(args.db):
        os.remove(args.db)

    store = TickStore(db_path=args.db)
    scenarios = [
        ("005930", "SIM_BREAKOUT", make_breakout_ticks),
        ("000660", "SIM_SELL_OFF", make_selloff_ticks),
        ("035720", "SIM_RANGE", make_range_ticks),
    ]

    print("simulation db:", args.db)

    for scenario_idx, scenario in enumerate(scenarios):
        code, name, factory = scenario
        start_time = datetime(2026, 5, 19, 9, 0, 0) + timedelta(hours=scenario_idx)
        ticks = factory(code=code, start_time=start_time, count=args.count)
        run_scenario(store, code, name, ticks, cycle_ticks=args.cycle_ticks, notify=args.notify)

    evaluate_pending_signals(store)
    print_counts(store)
    store.close()


def run_scenario(store, code, name, ticks, cycle_ticks, notify=False):
    """Load one fake scenario into the store and analyze it every N ticks."""
    for tick in ticks:
        store.add_tick(tick)

    event_cycles = 0
    signal_count = 0
    last_gpt_called_at = {}
    notifier = Notifier() if notify else None

    for end_idx in range(cycle_ticks, len(ticks) + 1, cycle_ticks):
        result = run_analysis_point(store, code, name, ticks[:end_idx], last_gpt_called_at, notifier)
        if result["events"]:
            event_cycles += 1
        if result["signal_id"]:
            signal_count += 1

    print(
        code,
        name,
        "analysis_cycles=" + str(len(range(cycle_ticks, len(ticks) + 1, cycle_ticks))),
        "event_cycles=" + str(event_cycles),
        "signals=" + str(signal_count)
    )


def run_analysis_point(store, code, name, ticks, last_gpt_called_at, notifier=None):
    """Run one simulated analysis point and persist the same logs as realtime."""
    summary = summarize_multi_timeframes_for_gpt(
        code=code,
        name=name,
        ticks=ticks,
        drop_last=True
    )

    if not summary:
        return {"events": [], "signal_id": None}

    summary["market_context"] = make_simulated_market_context(code, name, summary)
    summary["historical_price_context"] = store.get_historical_price_context(code)
    summary["historical_signal_stats"] = store.get_signal_performance_context(code)
    events = detect_gpt_events(summary)
    summary["events"] = events

    detected_at = ticks[-1]["received_at"]
    detected_dt = parse_dt(detected_at)

    if not events:
        return {"events": events, "signal_id": None}

    if not can_call_gpt(code, detected_dt, last_gpt_called_at):
        store.save_event_logs(
            summary=summary,
            events=events,
            detected_at=detected_at,
            gpt_requested=False,
            skip_reason="cooldown"
        )
        return {"events": events, "signal_id": None}

    signal = generate_validation_signal(summary)
    if signal:
        summary["validation_signal"] = signal
        signal_id = store.save_signal_log(
            signal=signal,
            summary=summary,
            detected_at=detected_at
        )
    else:
        signal_id = None

    if notifier:
        results = notifier.notify_event(summary=summary, events=events, signal=signal)
        if results:
            store.save_notification_logs(
                summary=summary,
                events=events,
                results=results,
                message=results[0].get("message"),
                sent_at=detected_at
            )

    store.save_event_logs(
        summary=summary,
        events=events,
        detected_at=detected_at,
        gpt_requested=True
    )

    store.save_gpt_call_log(
        started_at=detected_at,
        finished_at=detected_at,
        status="simulated",
        requested_count=1,
        codes=[code],
        result_preview="offline simulation"
    )
    store.save_analysis_result(
        summary=summary,
        gpt_result="offline simulation",
        analyzed_at=detected_at
    )
    last_gpt_called_at[code] = detected_dt

    return {"events": events, "signal_id": signal_id}


def can_call_gpt(code, detected_dt, last_gpt_called_at):
    """Apply the same per-symbol GPT cooldown used by the realtime app."""
    if not detected_dt:
        return True

    last_called_at = last_gpt_called_at.get(code)

    if not last_called_at:
        return True

    return (detected_dt - last_called_at).total_seconds() >= GPT_COOLDOWN_SEC


def evaluate_pending_signals(store):
    """Evaluate saved signals against later simulated ticks."""
    pending = fetch_pending_signals(store, limit=1000)
    evaluated = 0

    for signal in pending:
        result = evaluate_signal(store, signal)
        if result:
            store.save_paper_trade_result(result)
            evaluated += 1

    print("paper results evaluated:", evaluated)


def print_counts(store):
    """Print row counts for the tables touched by the simulation."""
    table_names = [
        "ticks",
        "analysis_results",
        "event_logs",
        "gpt_call_logs",
        "signal_logs",
        "paper_trade_results",
        "notification_logs",
    ]

    for table_name in table_names:
        count = store.conn.execute("SELECT COUNT(*) FROM {}".format(table_name)).fetchone()[0]
        print("{}: {}".format(table_name, count))


def make_breakout_ticks(code, start_time, count):
    """Generate a range-to-breakout scenario with volume expansion."""
    ticks = []
    price = 74000
    trigger_start = int(count * 0.45)
    trigger_end = int(count * 0.60)

    for i in range(count):
        if i < trigger_start:
            price += wave(i, width=9, scale=8)
            volume = 20 + (i % 5)
        elif i < trigger_end:
            price += 8 + (i % 4)
            volume = 450 + (i % 30)
        else:
            price += wave(i, width=13, scale=5)
            volume = 65 + (i % 12)

        ticks.append(make_tick(code, start_time, i, price, volume, strength=135.0))

    return ticks


def make_selloff_ticks(code, start_time, count):
    """Generate a range-to-selloff scenario with volume expansion."""
    ticks = []
    price = 125000
    trigger_start = int(count * 0.45)
    trigger_end = int(count * 0.60)

    for i in range(count):
        if i < trigger_start:
            price += wave(i, width=11, scale=12)
            volume = 25 + (i % 7)
        elif i < trigger_end:
            price -= 9 + (i % 5)
            volume = 320 + (i % 20)
        else:
            price += wave(i, width=15, scale=6)
            volume = 70 + (i % 10)

        ticks.append(make_tick(code, start_time, i, price, volume, strength=72.0))

    return ticks


def make_range_ticks(code, start_time, count):
    """Generate a low-event sideways scenario."""
    ticks = []
    base = 58000

    for i in range(count):
        price = base + wave(i, width=18, scale=22)
        volume = 30 + (i % 4)
        ticks.append(make_tick(code, start_time, i, price, volume, strength=98.0))

    return ticks


def make_tick(code, start_time, index, price, volume, strength):
    """Create one fake Kiwoom-like tick dictionary."""
    received_at = start_time + timedelta(seconds=index * 10)
    day_open = price - 150
    day_high = price + 80
    day_low = price - 180

    return {
        "code": code,
        "trade_time": received_at.strftime("%H%M%S"),
        "price": int(price),
        "change_rate": round((price - day_open) / day_open * 100, 3),
        "acc_volume": int(100000 + index * volume),
        "tick_volume": int(volume),
        "open_price": int(day_open),
        "high_price": int(day_high),
        "low_price": int(day_low),
        "strength": strength,
        "received_at": received_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
    }


def make_simulated_market_context(code, name, summary):
    """Create fake derivatives/orderbook/program context for offline tests."""
    primary = summary.get("timeframes", {}).get("1m", {})
    latest = primary.get("latest", {})
    close = latest.get("close") or 0

    if "BREAKOUT" in name:
        total_bid_qty = 900000
        total_ask_qty = 320000
    elif "SELL_OFF" in name:
        total_bid_qty = 260000
        total_ask_qty = 840000
    else:
        total_bid_qty = 500000
        total_ask_qty = 520000

    total_qty = total_bid_qty + total_ask_qty
    imbalance = round((total_bid_qty - total_ask_qty) / total_qty, 4) if total_qty else None
    best_bid = int(close - 50) if close else None
    best_ask = int(close + 50) if close else None

    return {
        "asof": summary.get("market_snapshot", {}).get("received_at"),
        "market_indices": {
            "kospi": 2720.35,
            "kospi_change_pct": 0.48 if "BREAKOUT" in name else -0.42,
            "kosdaq": 845.12,
            "kosdaq_change_pct": 0.22 if "BREAKOUT" in name else -0.36,
            "kospi200": 381.05,
            "kospi200_change_pct": 0.31 if "BREAKOUT" in name else -0.28,
            "usd_krw": 1348.5,
            "usd_krw_change_pct": -0.12 if "BREAKOUT" in name else 0.18,
        },
        "sector_context": {
            "sector_name": "Semiconductor" if code in ("005930", "000660") else "Internet",
            "sector_index": 1280.4,
            "sector_change_pct": 0.7 if "BREAKOUT" in name else -0.5,
            "relative_strength_vs_sector_pct": 0.4 if "BREAKOUT" in name else -0.3,
            "peer_movers": [
                {"name": "peer_a", "change_pct": 0.9 if "BREAKOUT" in name else -0.4},
                {"name": "peer_b", "change_pct": 0.5 if "BREAKOUT" in name else -0.7},
            ],
        },
        "reference_levels": {
            "previous_close": int(close - 300) if close else None,
            "previous_high": int(close + 200) if close else None,
            "previous_low": int(close - 700) if close else None,
            "today_open_gap_pct": 0.35 if "BREAKOUT" in name else -0.2,
            "intraday_high_breakout": True if "BREAKOUT" in name else False,
            "intraday_low_breakdown": True if "SELL_OFF" in name else False,
            "recent_20d_high": int(close + 1000) if close else None,
            "recent_20d_low": int(close - 1800) if close else None,
            "distance_from_20d_high_pct": -1.2 if "BREAKOUT" in name else -4.8,
            "distance_from_20d_low_pct": 5.1 if "BREAKOUT" in name else 1.4,
        },
        "derivatives": {
            "kospi200_futures_price": 380.25,
            "kospi200_futures_change_pct": 0.32 if "BREAKOUT" in name else -0.25,
            "basis": 0.45 if "BREAKOUT" in name else -0.35,
            "foreign_futures_net_contracts": 1800 if "BREAKOUT" in name else -1500,
            "institution_futures_net_contracts": -900 if "BREAKOUT" in name else 700,
            "put_call_ratio": 0.88 if "BREAKOUT" in name else 1.18,
            "implied_volatility": 18.5,
        },
        "short_selling": {
            "short_sale_volume": 120000,
            "short_sale_value": 8700000000,
            "short_sale_ratio_pct": 3.5 if "BREAKOUT" in name else 7.8,
            "short_balance_qty": 5800000,
            "short_balance_ratio_pct": 0.1,
        },
        "credit": {
            "credit_balance_qty": 2100000,
            "credit_balance_ratio_pct": 0.04,
            "credit_balance_change_qty": -12000 if "SELL_OFF" in name else 18000,
            "loan_balance_qty": 450000,
            "loan_balance_change_qty": 8000,
        },
        "orderbook": {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": 100 if close else None,
            "spread_pct": round(100 / close * 100, 4) if close else None,
            "total_bid_qty": total_bid_qty,
            "total_ask_qty": total_ask_qty,
            "bid_ask_imbalance": imbalance,
            "bid_levels": [],
            "ask_levels": [],
        },
        "program_trading": {
            "program_net_value": 12500000000 if "BREAKOUT" in name else -9800000000,
            "program_buy_value": 86000000000,
            "program_sell_value": 73500000000,
            "foreign_net_value": 9800000000 if "BREAKOUT" in name else -6600000000,
            "institution_net_value": -4300000000,
        },
        "news": {
            "asof": summary.get("market_snapshot", {}).get("received_at"),
            "summary": "Positive product-demand headlines" if "BREAKOUT" in name else "Mixed demand and margin concerns",
            "sentiment": "positive" if "BREAKOUT" in name else "negative",
            "source_count": 3,
            "items": [
                {
                    "time": summary.get("market_snapshot", {}).get("received_at"),
                    "title": "Simulated intraday headline",
                    "source": "simulation",
                    "sentiment": "positive" if "BREAKOUT" in name else "negative",
                }
            ],
        },
        "disclosures": {
            "asof": summary.get("market_snapshot", {}).get("received_at"),
            "summary": "No material disclosure in simulation",
            "materiality": "none",
            "items": [],
        },
        "public_reaction": {
            "asof": summary.get("market_snapshot", {}).get("received_at"),
            "summary": "Retail reaction is optimistic but noisy" if "BREAKOUT" in name else "Retail reaction is cautious and rumor-driven",
            "sentiment": "positive" if "BREAKOUT" in name else "negative",
            "source_count": 2,
            "dominant_topics": ["momentum", "earnings"] if "BREAKOUT" in name else ["margin risk", "short-term fear"],
            "sample_size": 120,
            "weight": "very_low",
        },
        "data_quality": {
            "tick_last_received_at": summary.get("market_snapshot", {}).get("received_at"),
            "orderbook_last_received_at": summary.get("market_snapshot", {}).get("received_at"),
            "program_trading_last_received_at": summary.get("market_snapshot", {}).get("received_at"),
            "news_last_checked_at": summary.get("market_snapshot", {}).get("received_at"),
            "disclosure_last_checked_at": summary.get("market_snapshot", {}).get("received_at"),
            "public_reaction_last_checked_at": summary.get("market_snapshot", {}).get("received_at"),
            "missing_sections": [],
        },
        "notes": ["simulated market context"],
    }


def wave(index, width, scale):
    """Small deterministic wave used to make fake ticks less linear."""
    phase = index % width
    midpoint = width // 2
    return (phase - midpoint) * scale


if __name__ == "__main__":
    main()
