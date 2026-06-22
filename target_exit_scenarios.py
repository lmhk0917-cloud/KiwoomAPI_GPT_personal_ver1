"""Target/stop exit scenario validation from saved ticks.

This module is paper-only. It estimates what would have happened if a saved
long-candidate signal used a fixed target return and fixed stop within a
specific intraday holding window.
"""

from datetime import datetime, timedelta

from config import TRADE_BUY_FEE_PCT, TRADE_SELL_FEE_PCT, TRADE_SELL_TAX_PCT, TRADE_SLIPPAGE_PCT


ROUND_TRIP_COST_PCT = TRADE_BUY_FEE_PCT + TRADE_SELL_FEE_PCT + TRADE_SELL_TAX_PCT + (TRADE_SLIPPAGE_PCT * 2)
DEFAULT_SCENARIOS = (
    {"horizon_min": 10, "target_pct": 0.3, "stop_pct": 0.4},
    {"horizon_min": 30, "target_pct": 0.5, "stop_pct": 0.5},
    {"horizon_min": 30, "target_pct": 0.8, "stop_pct": 0.6},
    {"horizon_min": 60, "target_pct": 0.8, "stop_pct": 0.6},
    {"horizon_min": 60, "target_pct": 1.0, "stop_pct": 0.8},
)


def build_target_exit_scenarios(conn, days=5, code=None, scenarios=None, decision_side="long_candidate"):
    """Return fixed target/stop scenario metrics for recent quant-scored signals."""
    signal_rows = _fetch_signal_rows(conn, days=days, code=code, decision_side=decision_side)
    result = []
    for scenario in scenarios or DEFAULT_SCENARIOS:
        metrics = _evaluate_scenario(conn, signal_rows, scenario)
        result.append(metrics)
    return result


def _fetch_signal_rows(conn, days=5, code=None, decision_side="long_candidate"):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S.%f")
    clauses = ["q.scored_at >= ?"]
    params = [since]
    if code:
        clauses.append("q.code = ?")
        params.append(code)
    if decision_side:
        clauses.append("q.decision_side = ?")
        params.append(decision_side)

    rows = conn.execute("""
        SELECT
            q.signal_id,
            q.code,
            q.action_hint,
            q.decision_side,
            s.detected_at,
            s.current_price,
            p.return_10m_pct,
            p.return_30m_pct,
            p.return_60m_pct
        FROM quant_signal_scores q
        JOIN signal_logs s
            ON s.id = q.signal_id
        LEFT JOIN paper_trade_results p
            ON p.signal_id = q.signal_id
        WHERE {where}
        ORDER BY q.scored_at ASC, q.id ASC
    """.format(where=" AND ".join(clauses)), params).fetchall()
    return rows


def _evaluate_scenario(conn, rows, scenario):
    horizon_min = int(scenario["horizon_min"])
    target_pct = float(scenario["target_pct"])
    stop_pct = float(scenario["stop_pct"])
    horizon_key = "return_{}m_pct".format(horizon_min)
    evaluated = 0
    target_first = 0
    stop_first = 0
    timeout = 0
    exit_returns = []

    for row in rows:
        fallback_return = row[horizon_key] if horizon_key in row.keys() else None
        if fallback_return is None:
            continue
        entry_time = _parse_dt(row["detected_at"])
        entry_price = _to_float(row["current_price"])
        if entry_time is None or not entry_price:
            continue

        evaluated += 1
        end_time = entry_time + timedelta(minutes=horizon_min)
        target_price = entry_price * (1 + target_pct / 100.0)
        stop_price = entry_price * (1 - stop_pct / 100.0)
        target_time = _first_touch(conn, row["code"], entry_time, end_time, target_price, ">=")
        stop_time = _first_touch(conn, row["code"], entry_time, end_time, stop_price, "<=")

        if target_time and (not stop_time or target_time <= stop_time):
            target_first += 1
            exit_returns.append(target_pct)
        elif stop_time:
            stop_first += 1
            exit_returns.append(-stop_pct)
        else:
            timeout += 1
            exit_returns.append(float(fallback_return))

    wins = [value for value in exit_returns if value > 0]
    return {
        "horizon_min": horizon_min,
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "evaluated_count": evaluated,
        "target_first_count": target_first,
        "stop_first_count": stop_first,
        "timeout_count": timeout,
        "target_first_rate_pct": _rate(target_first, evaluated),
        "stop_first_rate_pct": _rate(stop_first, evaluated),
        "win_rate_pct": _rate(len(wins), evaluated),
        "avg_exit_return_pct": _avg(exit_returns),
        "avg_net_exit_return_pct": _avg([value - ROUND_TRIP_COST_PCT for value in exit_returns]),
        "best_exit_return_pct": round(max(exit_returns), 4) if exit_returns else None,
        "worst_exit_return_pct": round(min(exit_returns), 4) if exit_returns else None,
    }


def _first_touch(conn, code, start_time, end_time, price, comparator):
    row = conn.execute("""
        SELECT MIN(received_at) AS touched_at
        FROM ticks
        WHERE code = ?
          AND received_at >= ?
          AND received_at <= ?
          AND price {comparator} ?
    """.format(comparator=comparator), (
        code,
        _format_dt(start_time),
        _format_dt(end_time),
        price,
    )).fetchone()
    return _parse_dt(row["touched_at"]) if row and row["touched_at"] else None


def _parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _format_dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _avg(values):
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _rate(count, total):
    if not total:
        return None
    return round(float(count) / float(total) * 100.0, 4)
