"""Quant-style feedback snapshots from paper-trade outcomes.

This module keeps the project in the current read-only/paper-trade scope:
it does not place orders, size positions, or change live trading behavior.
It turns saved signals and future tick evaluations into repeatable metrics
that GPT can interpret later.
"""

import argparse
import json
from datetime import datetime, timedelta

import config
from app_paths import DEFAULT_DB_PATH, setup_runtime_logging
from data_store import TickStore
from paper_trade_simulator import TickWindowCache, evaluate_signal, fetch_pending_signals


ROUND_TRIP_COST_PCT = (
    config.TRADE_BUY_FEE_PCT
    + config.TRADE_SELL_FEE_PCT
    + config.TRADE_SELL_TAX_PCT
    + (config.TRADE_SLIPPAGE_PCT * 2)
)
DEFAULT_CLUSTER_WINDOW_MINUTES = 10

LONG_ACTIONS = set((
    "WATCH_REBOUND",
    "WATCH_PULLBACK",
    "WATCH_BREAKOUT",
    "WATCH_SUPPORT",
    "WATCH_MOMENTUM",
    "VOL_EXPANSION_MOMENTUM",
    "HIGH_VOL_REVERSAL_WATCH",
))

CAUTION_ACTIONS = set((
    "AVOID_CHASE",
    "AVOID_DOWNTREND",
    "AVOID_SUPPLY",
    "WATCH_RESISTANCE",
    "OBSERVE_EVENT",
    "AVOID_VOLATILITY_TRAP",
))


def main():
    args = parse_args()
    setup_runtime_logging("quant_feedback")

    store = TickStore(db_path=args.db)
    try:
        if args.evaluate_pending:
            evaluated = evaluate_pending(
                store=store,
                since=_since_from_args(args),
                limit=args.evaluate_limit,
                allow_partial=args.allow_partial,
            )
            print("evaluated_pending:", evaluated)

        snapshots = save_feedback_snapshots(
            store=store,
            days=args.days,
            min_sample=args.min_sample,
            codes=parse_codes(args.codes),
        )
        print("saved_feedback_snapshots:", len(snapshots))
        for snapshot in snapshots:
            overview = snapshot.get("overview") or {}
            print(
                "{scope} code={code} signals={signals} evaluated={evaluated} "
                "avg60={avg60} pf60={pf60} label={label}".format(
                    scope=snapshot.get("scope"),
                    code=snapshot.get("code") or "ALL",
                    signals=overview.get("signal_count"),
                    evaluated=overview.get("evaluated_count"),
                    avg60=overview.get("avg_return_60m_pct"),
                    pf60=overview.get("profit_factor_60m"),
                    label=(snapshot.get("guidance") or {}).get("label"),
                )
            )
    finally:
        store.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Build quant-style feedback from paper results.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--codes", default="")
    parser.add_argument("--min-sample", type=int, default=5)
    parser.add_argument("--evaluate-pending", action="store_true")
    parser.add_argument("--evaluate-limit", type=int, default=500)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--since", help="Only evaluate signals at or after this timestamp.")
    return parser.parse_args()


def parse_codes(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _since_from_args(args):
    if args.since:
        return args.since
    if args.days:
        return (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d %H:%M:%S.%f")
    return None


def evaluate_pending(store, since=None, limit=500, allow_partial=False, code=None):
    """Evaluate pending saved signals and return the number of inserted rows."""
    signals = fetch_pending_signals(store, limit=limit, code=code, since=since)
    tick_cache = TickWindowCache(store, signals)
    evaluated = 0
    for signal in signals:
        result = evaluate_signal(
            store,
            signal,
            allow_partial=allow_partial,
            tick_cache=tick_cache,
        )
        if result:
            store.save_paper_trade_result(result)
            evaluated += 1
    return evaluated


def save_feedback_snapshots(store, days=5, min_sample=5, codes=None):
    """Build and persist global plus per-code feedback snapshots."""
    snapshots = []
    global_snapshot = build_feedback_snapshot(
        conn=store.conn,
        days=days,
        min_sample=min_sample,
        code=None,
    )
    snapshots.append(global_snapshot)
    store.save_quant_feedback_snapshot(global_snapshot)

    code_list = codes or _codes_with_recent_signals(store.conn, days=days)
    for code in code_list:
        snapshot = build_feedback_snapshot(
            conn=store.conn,
            days=days,
            min_sample=min_sample,
            code=code,
        )
        snapshots.append(snapshot)
        store.save_quant_feedback_snapshot(snapshot)

    return snapshots


def build_feedback_snapshot(conn, days=5, min_sample=5, code=None):
    """Return a quant-style performance snapshot for signals and paper results."""
    where_sql, params, window_start = _where(days=days, code=code)
    rows = conn.execute("""
        SELECT
            s.id AS signal_id,
            s.detected_at,
            s.code,
            s.action_hint,
            s.confidence_score,
            s.risk_level,
            r.id AS result_id,
            r.evaluated_at,
            r.return_5m_pct,
            r.return_10m_pct,
            r.return_30m_pct,
            r.return_60m_pct,
            r.max_gain_30m_pct,
            r.max_loss_30m_pct,
            r.max_gain_60m_pct,
            r.max_loss_60m_pct,
            r.target_1_hit,
            r.target_2_hit,
            r.stop_loss_hit,
            r.outcome_label
        FROM signal_logs s
        LEFT JOIN paper_trade_results r
            ON r.signal_id = s.id
        {where_sql}
        ORDER BY s.detected_at ASC
    """.format(where_sql=where_sql), params).fetchall()

    overview = _metric_block(rows)
    by_action = []
    for action in sorted(set(row["action_hint"] or "UNKNOWN" for row in rows)):
        action_rows = [row for row in rows if (row["action_hint"] or "UNKNOWN") == action]
        block = _metric_block(action_rows)
        block["action_hint"] = action
        block["decision_side"] = _decision_side(action)
        by_action.append(block)
    by_action.sort(key=lambda item: (item.get("evaluated_count") or 0, item.get("profit_factor_60m") or 0), reverse=True)

    guidance = _build_guidance(overview, by_action, min_sample=min_sample)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "scope": "code" if code else "global",
        "code": code,
        "window_start": window_start,
        "window_end": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "min_sample": min_sample,
        "overview": overview,
        "by_action": by_action,
        "guidance": guidance,
    }


def _where(days=None, code=None):
    clauses = []
    params = []
    window_start = None
    if days:
        window_start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S.%f")
        clauses.append("s.detected_at >= ?")
        params.append(window_start)
    if code:
        clauses.append("s.code = ?")
        params.append(code)
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where_sql, params, window_start


def _codes_with_recent_signals(conn, days=5):
    where_sql, params, _window_start = _where(days=days)
    rows = conn.execute("""
        SELECT DISTINCT s.code
        FROM signal_logs s
        {where_sql}
        ORDER BY s.code
    """.format(where_sql=where_sql), params).fetchall()
    return [row["code"] for row in rows]


def _metric_block(rows):
    evaluated = [row for row in rows if row["result_id"] is not None]
    return_5m = _values(evaluated, "return_5m_pct")
    return_10m = _values(evaluated, "return_10m_pct")
    return_30m = _values(evaluated, "return_30m_pct")
    return_60m = _values(evaluated, "return_60m_pct")
    metrics = {
        "signal_count": len(rows),
        "evaluated_count": len(evaluated),
        "pending_count": len(rows) - len(evaluated),
        "evaluated_5m_count": len(return_5m),
        "evaluated_10m_count": len(return_10m),
        "evaluated_30m_count": len(return_30m),
        "evaluated_60m_count": len(return_60m),
        "avg_return_5m_pct": _avg(return_5m),
        "avg_return_10m_pct": _avg(return_10m),
        "avg_return_30m_pct": _avg(return_30m),
        "avg_return_60m_pct": _avg(return_60m),
        "avg_net_return_30m_pct": _avg([value - ROUND_TRIP_COST_PCT for value in return_30m]),
        "avg_net_return_60m_pct": _avg([value - ROUND_TRIP_COST_PCT for value in return_60m]),
        "win_rate_30m_pct": _win_rate(return_30m),
        "win_rate_60m_pct": _win_rate(return_60m),
        "net_win_rate_60m_pct": _win_rate([value - ROUND_TRIP_COST_PCT for value in return_60m]),
        "profit_factor_30m": _profit_factor(return_30m),
        "profit_factor_60m": _profit_factor(return_60m),
        "expectancy_30m_pct": _avg([value - ROUND_TRIP_COST_PCT for value in return_30m]),
        "expectancy_60m_pct": _avg([value - ROUND_TRIP_COST_PCT for value in return_60m]),
        "avg_mfe_60m_pct": _avg(_values(evaluated, "max_gain_60m_pct")),
        "avg_mae_60m_pct": _avg(_values(evaluated, "max_loss_60m_pct")),
        "target_1_hit_rate_pct": _hit_rate(evaluated, "target_1_hit"),
        "target_2_hit_rate_pct": _hit_rate(evaluated, "target_2_hit"),
        "stop_loss_hit_rate_pct": _hit_rate(evaluated, "stop_loss_hit"),
        "outcome_counts": _counts(evaluated, "outcome_label"),
    }
    metrics.update(_cluster_metrics(rows))
    return metrics


def _build_guidance(overview, by_action, min_sample=5):
    avoid_actions = []
    prefer_actions = []
    watch_actions = []
    missed_upside_actions = []
    for item in by_action:
        if (item.get("evaluated_count") or 0) < min_sample:
            continue
        action = item.get("action_hint")
        avg60 = item.get("avg_return_60m_pct")
        net60 = item.get("avg_net_return_60m_pct")
        win60 = item.get("win_rate_60m_pct")
        pf60 = item.get("profit_factor_60m")
        stop = item.get("stop_loss_hit_rate_pct")
        side = _decision_side(action)
        if (
            side == "caution_or_avoid"
            and net60 is not None
            and net60 > 0
            and win60 is not None
            and win60 >= 50
            and (pf60 or 0) >= 1
        ):
            missed_upside_actions.append(_action_guidance(action, item, "relax_avoid_or_require_trap_confirmation"))
        elif net60 is not None and net60 > 0 and win60 is not None and win60 >= 50 and (pf60 or 0) >= 1:
            prefer_actions.append(_action_guidance(action, item, "prefer_when_live_setup_matches"))
        elif (
            (net60 is not None and net60 < 0)
            or (win60 is not None and win60 < 45)
            or (stop is not None and stop >= 50)
        ):
            avoid_actions.append(_action_guidance(action, item, "lower_confidence_or_require_confirmation"))
        elif avg60 is not None:
            watch_actions.append(_action_guidance(action, item, "neutral_keep_as_watch"))

    label = "sample_too_small"
    if (overview.get("evaluated_count") or 0) >= min_sample:
        net60 = overview.get("avg_net_return_60m_pct")
        pf60 = overview.get("profit_factor_60m") or 0
        if net60 is not None and net60 > 0 and pf60 >= 1:
            label = "positive_expectancy"
        elif net60 is not None and net60 < 0:
            label = "negative_expectancy"
        else:
            label = "neutral_expectancy"

    return {
        "label": label,
        "cost_pct": ROUND_TRIP_COST_PCT,
        "avoid_actions": avoid_actions[:5],
        "prefer_actions": prefer_actions[:3],
        "missed_upside_actions": missed_upside_actions[:5],
        "watch_actions": watch_actions[:3],
        "summary": _guidance_summary(label, avoid_actions, prefer_actions, missed_upside_actions),
    }


def _action_guidance(action, item, adjustment):
    return {
        "action_hint": action,
        "evaluated_count": item.get("evaluated_count"),
        "avg_net_return_60m_pct": item.get("avg_net_return_60m_pct"),
        "win_rate_60m_pct": item.get("win_rate_60m_pct"),
        "profit_factor_60m": item.get("profit_factor_60m"),
        "stop_loss_hit_rate_pct": item.get("stop_loss_hit_rate_pct"),
        "adjustment": adjustment,
    }


def _guidance_summary(label, avoid_actions, prefer_actions, missed_upside_actions=None):
    missed_upside_actions = missed_upside_actions or []
    if missed_upside_actions:
        return "Some caution/avoid labels missed upside; require stronger trap confirmation before avoidance."
    if label == "negative_expectancy":
        return "Recent evaluated signals have negative net expectancy; require stronger confirmation."
    if label == "positive_expectancy":
        return "Recent evaluated signals have positive net expectancy; use action-level filters."
    if prefer_actions:
        return "Some actions have usable evidence, but global expectancy is mixed."
    if avoid_actions:
        return "Several actions need lower confidence or stricter confirmation."
    return "Insufficient or mixed feedback; do not overfit."


def _decision_side(action):
    if action in LONG_ACTIONS:
        return "long_candidate"
    if action in CAUTION_ACTIONS:
        return "caution_or_avoid"
    return "unknown"


def _values(rows, key):
    return [float(row[key]) for row in rows if row[key] is not None]


def _avg(values):
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _win_rate(values):
    if not values:
        return None
    return round(len([value for value in values if value > 0]) / len(values) * 100, 2)


def _profit_factor(values):
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if not values:
        return None
    if losses == 0:
        return None if gains == 0 else 999.0
    return round(gains / losses, 4)


def _hit_rate(rows, key):
    values = [row[key] for row in rows if row[key] is not None]
    if not values:
        return None
    return round(len([value for value in values if int(value) == 1]) / len(values) * 100, 2)


def _counts(rows, key):
    counts = {}
    for row in rows:
        value = row[key] if row[key] is not None else "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _cluster_metrics(rows, window_minutes=DEFAULT_CLUSTER_WINDOW_MINUTES):
    clusters = _cluster_representatives(rows, window_minutes=window_minutes)
    evaluated = [row for row in clusters if row["result_id"] is not None]
    return_30m = _values(clusters, "return_30m_pct")
    return_60m = _values(clusters, "return_60m_pct")
    return {
        "cluster_window_minutes": window_minutes,
        "cluster_count": len(clusters),
        "evaluated_cluster_count": len(evaluated),
        "evaluated_cluster_30m_count": len(return_30m),
        "evaluated_cluster_60m_count": len(return_60m),
        "avg_cluster_return_30m_pct": _avg(return_30m),
        "avg_cluster_return_60m_pct": _avg(return_60m),
        "avg_cluster_net_return_60m_pct": _avg([value - ROUND_TRIP_COST_PCT for value in return_60m]),
        "cluster_win_rate_60m_pct": _win_rate(return_60m),
        "cluster_net_win_rate_60m_pct": _win_rate([value - ROUND_TRIP_COST_PCT for value in return_60m]),
        "cluster_profit_factor_60m": _profit_factor(return_60m),
        "cluster_stop_loss_hit_rate_pct": _hit_rate(evaluated, "stop_loss_hit"),
    }


def _cluster_representatives(rows, window_minutes=DEFAULT_CLUSTER_WINDOW_MINUTES):
    clusters = []
    active = {}
    window_delta = timedelta(minutes=window_minutes)
    sorted_rows = sorted(rows, key=lambda row: (
        row["code"] or "",
        row["action_hint"] or "",
        row["detected_at"] or "",
    ))

    for row in sorted_rows:
        detected_at = _parse_dt(row["detected_at"])
        if not detected_at:
            continue
        key = (row["code"], row["action_hint"])
        current = active.get(key)
        if current is None or detected_at - current["started_at"] > window_delta:
            current = {"started_at": detected_at, "rows": []}
            active[key] = current
            clusters.append(current)
        current["rows"].append(row)

    representatives = []
    for cluster in clusters:
        representative = None
        for row in cluster["rows"]:
            if row["return_60m_pct"] is not None:
                representative = row
                break
        if representative is None:
            for row in cluster["rows"]:
                if row["result_id"] is not None:
                    representative = row
                    break
        representatives.append(representative or cluster["rows"][0])
    return representatives


def _parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


if __name__ == "__main__":
    raise SystemExit(main())
