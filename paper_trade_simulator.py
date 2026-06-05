"""Paper-trade evaluator for saved validation signals.

The evaluator does not place trades. It measures what happened after a saved
signal so the event rules can be tuned with evidence.
"""

import argparse
from datetime import datetime, timedelta

from app_paths import DEFAULT_DB_PATH
from data_store import TickStore


HORIZONS_MIN = [5, 10, 30, 60]
COMPLETION_GRACE_MINUTES = 5
TRADEABLE_LONG_ACTIONS = (
    "WATCH_REBOUND",
    "WATCH_PULLBACK",
    "WATCH_BREAKOUT",
    "WATCH_SUPPORT",
    "WATCH_MOMENTUM",
)

CAUTION_ACTIONS = (
    "AVOID_CHASE",
    "AVOID_DOWNTREND",
    "AVOID_SUPPLY",
    "WATCH_RESISTANCE",
    "OBSERVE_EVENT",
)

EVALUATED_ACTIONS = TRADEABLE_LONG_ACTIONS + CAUTION_ACTIONS


def main():
    """CLI entrypoint for evaluating pending signals in SQLite."""
    parser = argparse.ArgumentParser(description="Evaluate stored validation signals with future tick data.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--code", help="Optional stock code filter")
    parser.add_argument("--since", help="Only evaluate signals detected at or after this timestamp")
    args = parser.parse_args()

    store = TickStore(db_path=args.db)
    signals = fetch_pending_signals(store, limit=args.limit, code=args.code, since=args.since)

    evaluated = 0
    for signal in signals:
        result = evaluate_signal(store, signal)
        if result:
            store.save_paper_trade_result(result)
            evaluated += 1

    store.close()
    print("evaluated signals:", evaluated)


def fetch_pending_signals(store, limit=100, code=None, since=None):
    """Fetch signals that do not yet have an evaluation row."""
    params = []
    where = """
        WHERE NOT EXISTS (
            SELECT 1
            FROM paper_trade_results r
            WHERE r.signal_id = signal_logs.id
        )
    """

    if code:
        where += " AND code = ?"
        params.append(code)

    if since:
        where += " AND detected_at >= ?"
        params.append(since)

    placeholders = ",".join("?" for _ in EVALUATED_ACTIONS)
    where += " AND action_hint IN ({})".format(placeholders)
    params.extend(EVALUATED_ACTIONS)

    params.append(limit)

    sql = """
        SELECT *
        FROM signal_logs
        {}
        ORDER BY detected_at ASC
        LIMIT ?
    """.format(where)

    return store.conn.execute(sql, params).fetchall()


def evaluate_signal(store, signal):
    """Evaluate future returns after one signal when enough tick data exists."""
    entry_time = parse_dt(signal["detected_at"])
    entry_price = _to_float(signal["current_price"])

    if not entry_time or not entry_price:
        return None

    end_time = entry_time + timedelta(minutes=max(HORIZONS_MIN))
    fetch_end_time = end_time + timedelta(minutes=COMPLETION_GRACE_MINUTES)
    last_tick_time = fetch_last_tick_time(store, signal["code"], entry_time, fetch_end_time)
    if not last_tick_time or last_tick_time < end_time:
        return None

    stats_30m = fetch_price_stats(store, signal["code"], entry_time, entry_time + timedelta(minutes=30))
    stats_60m = fetch_price_stats(store, signal["code"], entry_time, end_time)

    if not stats_60m or stats_60m["max_price"] is None or stats_60m["min_price"] is None:
        return None

    result = {
        "signal_id": signal["id"],
        "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "code": signal["code"],
        "entry_time": signal["detected_at"],
        "entry_price": entry_price,
        "max_gain_30m_pct": pct_from_entry(stats_30m["max_price"], entry_price) if stats_30m else None,
        "max_loss_30m_pct": pct_from_entry(stats_30m["min_price"], entry_price) if stats_30m else None,
        "max_gain_60m_pct": pct_from_entry(stats_60m["max_price"], entry_price),
        "max_loss_60m_pct": pct_from_entry(stats_60m["min_price"], entry_price),
    }

    for minutes in HORIZONS_MIN:
        horizon_price = fetch_price_at_or_after(store, signal["code"], entry_time + timedelta(minutes=minutes), fetch_end_time)
        key = "return_{}m_pct".format(minutes)
        result[key] = pct_from_entry(horizon_price, entry_price)

    target_1 = _to_float(signal["target_1"]) if "target_1" in signal.keys() else None
    target_2 = _to_float(signal["target_2"]) if "target_2" in signal.keys() else None
    stop_loss = _to_float(signal["stop_loss"]) if "stop_loss" in signal.keys() else None
    hit_info = evaluate_levels_sql(
        store,
        signal["code"],
        entry_time,
        end_time,
        target_1=target_1,
        target_2=target_2,
        stop_loss=stop_loss,
    )
    result.update(hit_info)
    result["decision_side"] = classify_decision_side(signal["action_hint"])
    result["directional_success_30m"] = directional_success(
        signal["action_hint"],
        result.get("return_30m_pct"),
        result.get("max_gain_30m_pct"),
        result.get("max_loss_30m_pct"),
    )
    result["directional_success_60m"] = directional_success(
        signal["action_hint"],
        result.get("return_60m_pct"),
        result.get("max_gain_60m_pct"),
        result.get("max_loss_60m_pct"),
    )

    return result


def fetch_last_tick_time(store, code, start_time, end_time):
    row = store.conn.execute("""
        SELECT MAX(received_at) AS last_at
        FROM ticks
        WHERE code = ?
          AND received_at >= ?
          AND received_at <= ?
    """, (
        code,
        format_dt(start_time),
        format_dt(end_time),
    )).fetchone()
    return parse_dt(row["last_at"]) if row and row["last_at"] else None


def fetch_price_stats(store, code, start_time, end_time):
    return store.conn.execute("""
        SELECT MAX(price) AS max_price, MIN(price) AS min_price
        FROM ticks
        WHERE code = ?
          AND received_at >= ?
          AND received_at <= ?
    """, (
        code,
        format_dt(start_time),
        format_dt(end_time),
    )).fetchone()


def fetch_price_at_or_after(store, code, target_time, fetch_end_time):
    row = store.conn.execute("""
        SELECT price
        FROM ticks
        WHERE code = ?
          AND received_at >= ?
          AND received_at <= ?
        ORDER BY received_at ASC
        LIMIT 1
    """, (
        code,
        format_dt(target_time),
        format_dt(fetch_end_time),
    )).fetchone()
    return _to_float(row["price"]) if row else None


def evaluate_levels_sql(store, code, start_time, end_time, target_1=None, target_2=None, stop_loss=None):
    target_1_time = first_touch_time_sql(store, code, start_time, end_time, target_1, direction="above")
    target_2_time = first_touch_time_sql(store, code, start_time, end_time, target_2, direction="above")
    stop_time = first_touch_time_sql(store, code, start_time, end_time, stop_loss, direction="below")

    target_1_hit = target_1_time is not None
    target_2_hit = target_2_time is not None
    stop_loss_hit = stop_time is not None

    if stop_loss_hit and (not target_1_hit or stop_time < target_1_time):
        outcome_label = "stop_before_target"
    elif target_2_hit and (not stop_loss_hit or target_2_time <= stop_time):
        outcome_label = "target_2_before_stop"
    elif target_1_hit and (not stop_loss_hit or target_1_time <= stop_time):
        outcome_label = "target_1_before_stop"
    elif target_2_hit:
        outcome_label = "target_2_after_stop"
    elif target_1_hit:
        outcome_label = "target_1_after_stop"
    else:
        outcome_label = "no_level_hit_60m"

    return {
        "target_1_hit": target_1_hit,
        "target_2_hit": target_2_hit,
        "stop_loss_hit": stop_loss_hit,
        "target_1_hit_at": format_dt(target_1_time),
        "target_2_hit_at": format_dt(target_2_time),
        "stop_loss_hit_at": format_dt(stop_time),
        "outcome_label": outcome_label,
    }


def first_touch_time_sql(store, code, start_time, end_time, level, direction):
    if level is None:
        return None

    comparator = ">=" if direction == "above" else "<="
    row = store.conn.execute("""
        SELECT MIN(received_at) AS touched_at
        FROM ticks
        WHERE code = ?
          AND received_at >= ?
          AND received_at <= ?
          AND price {comparator} ?
    """.format(comparator=comparator), (
        code,
        format_dt(start_time),
        format_dt(end_time),
        level,
    )).fetchone()
    return parse_dt(row["touched_at"]) if row and row["touched_at"] else None


def pct_from_entry(price, entry_price):
    if price is None or entry_price in (None, 0):
        return None
    return round((price - entry_price) / entry_price * 100, 3)


def classify_decision_side(action_hint):
    """Classify a saved signal by the action it implied for later review."""
    if action_hint in TRADEABLE_LONG_ACTIONS:
        return "long_candidate"
    if action_hint in CAUTION_ACTIONS:
        return "avoid_or_caution"
    return "unknown"


def directional_success(action_hint, return_pct, max_gain_pct_value=None, max_loss_pct_value=None):
    """Judge whether the signal's intent matched later price action."""
    if return_pct is None:
        return None

    if action_hint in TRADEABLE_LONG_ACTIONS:
        return return_pct > 0

    if action_hint in CAUTION_ACTIONS:
        if return_pct <= 0:
            return True
        if max_gain_pct_value is not None and max_loss_pct_value is not None:
            return abs(max_loss_pct_value) >= max_gain_pct_value
        return False

    return None


def fetch_future_ticks(store, code, start_time, end_time):
    """Read ticks from signal time through the longest evaluation horizon."""
    return store.conn.execute("""
        SELECT received_at, price
        FROM ticks
        WHERE code = ?
          AND received_at >= ?
          AND received_at <= ?
        ORDER BY received_at ASC
    """, (
        code,
        start_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
        end_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
    )).fetchall()


def find_price_at_or_after(ticks, target_time):
    """Find the first tick price at or after a target horizon."""
    for row in ticks:
        received_at = parse_dt(row["received_at"])
        if received_at and received_at >= target_time:
            return _to_float(row["price"])

    return _to_float(ticks[-1]["price"]) if ticks else None


def ticks_until(ticks, end_time):
    """Collect ticks through a horizon timestamp."""
    selected = []
    for row in ticks:
        received_at = parse_dt(row["received_at"])
        price = _to_float(row["price"])
        if received_at and received_at <= end_time and price is not None:
            selected.append(row)
    return selected


def tick_prices_until(ticks, end_time):
    """Collect prices through a horizon timestamp."""
    return [_to_float(row["price"]) for row in ticks_until(ticks, end_time)]


def max_gain_pct(prices, entry_price):
    if not prices:
        return None
    return round((max(prices) - entry_price) / entry_price * 100, 3)


def max_loss_pct(prices, entry_price):
    if not prices:
        return None
    return round((min(prices) - entry_price) / entry_price * 100, 3)


def evaluate_levels(ticks, target_1=None, target_2=None, stop_loss=None):
    """Evaluate whether rough validation levels were touched within 60 minutes."""
    target_1_time = first_touch_time(ticks, target_1, direction="above")
    target_2_time = first_touch_time(ticks, target_2, direction="above")
    stop_time = first_touch_time(ticks, stop_loss, direction="below")

    target_1_hit = target_1_time is not None
    target_2_hit = target_2_time is not None
    stop_loss_hit = stop_time is not None

    if stop_loss_hit and (not target_1_hit or stop_time < target_1_time):
        outcome_label = "stop_before_target"
    elif target_2_hit and (not stop_loss_hit or target_2_time <= stop_time):
        outcome_label = "target_2_before_stop"
    elif target_1_hit and (not stop_loss_hit or target_1_time <= stop_time):
        outcome_label = "target_1_before_stop"
    elif target_2_hit:
        outcome_label = "target_2_after_stop"
    elif target_1_hit:
        outcome_label = "target_1_after_stop"
    else:
        outcome_label = "no_level_hit_60m"

    return {
        "target_1_hit": target_1_hit,
        "target_2_hit": target_2_hit,
        "stop_loss_hit": stop_loss_hit,
        "target_1_hit_at": format_dt(target_1_time),
        "target_2_hit_at": format_dt(target_2_time),
        "stop_loss_hit_at": format_dt(stop_time),
        "outcome_label": outcome_label,
    }


def first_touch_time(ticks, level, direction):
    if level is None:
        return None

    for row in ticks:
        price = _to_float(row["price"])
        received_at = parse_dt(row["received_at"])
        if price is None or received_at is None:
            continue
        if direction == "above" and price >= level:
            return received_at
        if direction == "below" and price <= level:
            return received_at

    return None


def format_dt(value):
    if not value:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def parse_dt(value):
    """Parse timestamps saved by this project."""
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    return None


def _to_float(value):
    """Best-effort numeric conversion for SQLite values."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
