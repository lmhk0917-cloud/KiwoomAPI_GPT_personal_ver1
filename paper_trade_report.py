"""Paper-trade performance report for saved validation signals.

This is a quality-control tool. It answers two separate questions:
- Did long-candidate signals make money after the signal?
- Did avoid/caution signals correctly warn against weak follow-through?
"""

import argparse
import json
from datetime import datetime, timedelta

from app_paths import DEFAULT_DB_PATH
import config
from data_store import TickStore


ROUND_TRIP_COST_PCT = (
    config.TRADE_BUY_FEE_PCT
    + config.TRADE_SELL_FEE_PCT
    + config.TRADE_SELL_TAX_PCT
    + (config.TRADE_SLIPPAGE_PCT * 2)
)
DEFAULT_CLUSTER_WINDOW_MINUTES = 10

LONG_ACTIONS = (
    "WATCH_REBOUND",
    "WATCH_PULLBACK",
    "WATCH_BREAKOUT",
    "WATCH_SUPPORT",
    "WATCH_MOMENTUM",
    "VOL_EXPANSION_MOMENTUM",
    "HIGH_VOL_REVERSAL_WATCH",
)

CAUTION_ACTIONS = (
    "AVOID_CHASE",
    "AVOID_DOWNTREND",
    "AVOID_SUPPLY",
    "WATCH_RESISTANCE",
    "OBSERVE_EVENT",
    "AVOID_VOLATILITY_TRAP",
)


def main():
    args = parse_args()
    store = TickStore(db_path=args.db)

    try:
        if args.windows:
            report = build_window_comparison(
                conn=store.conn,
                windows=parse_windows(args.windows),
                code=args.code,
                min_sample=args.min_sample,
            )
        else:
            report = build_report(
                conn=store.conn,
                code=args.code,
                days=args.days,
                min_sample=args.min_sample,
                recent_limit=args.recent_limit,
            )
    finally:
        store.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.windows:
        print_window_comparison(report)
    else:
        print_text_report(report)


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize paper-trade performance from SQLite.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--code", help="Optional stock code filter")
    parser.add_argument("--days", type=int, help="Only include signals from the latest N days")
    parser.add_argument("--min-sample", type=int, default=5, help="Minimum evaluated rows before a label is trusted")
    parser.add_argument("--recent-limit", type=int, default=10, help="Recent evaluated signals to print")
    parser.add_argument("--windows", help="Comma-separated day windows to compare, for example 7,30,60")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    return parser.parse_args()


def parse_windows(value):
    windows = []
    for item in str(value).split(","):
        item = item.strip()
        if not item:
            continue
        try:
            days = int(item)
        except ValueError:
            raise argparse.ArgumentTypeError("windows must be comma-separated integers")
        if days <= 0:
            raise argparse.ArgumentTypeError("windows must be positive day counts")
        if days not in windows:
            windows.append(days)
    if not windows:
        raise argparse.ArgumentTypeError("at least one window is required")
    return windows


def build_window_comparison(conn, windows, code=None, min_sample=5):
    reports = []
    for days in windows:
        report = build_report(
            conn=conn,
            code=code,
            days=days,
            min_sample=min_sample,
            recent_limit=0,
        )
        reports.append(compact_window_report(report))
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "filters": {
            "code": code,
            "windows": windows,
            "min_sample": min_sample,
        },
        "windows": reports,
    }


def compact_window_report(report):
    overview = report.get("overview") or {}
    decision_rows = {
        row.get("group_name"): row
        for row in report.get("by_decision_side") or []
    }
    action_rows = report.get("by_action") or []
    code_action_rows = report.get("by_code_action") or []
    return {
        "days": (report.get("filters") or {}).get("days"),
        "sample_summary": report.get("sample_summary") or {},
        "overview": {
            "signal_count": overview.get("signal_count"),
            "evaluated_count": overview.get("evaluated_count"),
            "evaluated_60m_count": overview.get("evaluated_60m_count"),
            "pending_count": overview.get("pending_count"),
            "avg_net_return_60m_pct": overview.get("avg_net_return_60m_pct"),
            "net_win_rate_60m_pct": overview.get("net_win_rate_60m_pct"),
            "directional_success_60m_pct": overview.get("directional_success_60m_pct"),
            "stop_loss_hit_rate_pct": overview.get("stop_loss_hit_rate_pct"),
        },
        "long_candidate": compact_group_row(decision_rows.get("long_candidate")),
        "caution_or_avoid": compact_group_row(decision_rows.get("caution_or_avoid")),
        "best_actions": [
            compact_group_row(row)
            for row in sorted(
                action_rows,
                key=lambda row: (
                    row.get("profit_label") == "positive_net_expectancy",
                    row.get("avg_net_return_60m_pct") or -999,
                    row.get("evaluated_60m_count") or 0,
                ),
                reverse=True,
            )[:5]
        ],
        "weakest_code_actions": [
            compact_group_row(row)
            for row in sorted(
                code_action_rows,
                key=lambda row: (
                    row.get("avg_net_return_60m_pct")
                    if row.get("avg_net_return_60m_pct") is not None
                    else 999
                ),
            )[:5]
        ],
    }


def compact_group_row(row):
    if not row:
        return {}
    return {
        "group_name": row.get("group_name"),
        "signal_count": row.get("signal_count"),
        "evaluated_60m_count": row.get("evaluated_60m_count"),
        "avg_net_return_60m_pct": row.get("avg_net_return_60m_pct"),
        "net_win_rate_60m_pct": row.get("net_win_rate_60m_pct"),
        "directional_success_60m_pct": row.get("directional_success_60m_pct"),
        "stop_loss_hit_rate_pct": row.get("stop_loss_hit_rate_pct"),
        "profit_label": row.get("profit_label"),
        "directional_label": row.get("directional_label"),
        "interpretation_hint": row.get("interpretation_hint"),
        "quality_label": row.get("quality_label"),
        "tuning_hint": row.get("tuning_hint"),
    }


def build_report(conn, code=None, days=None, min_sample=5, recent_limit=10):
    where_sql, params = make_where_clause(code=code, days=days)

    overview = fetch_overview(conn, where_sql, params)
    action_rows = fetch_group_rows(conn, "s.action_hint", where_sql, params)
    decision_side_rows = fetch_group_rows(conn, decision_side_expr(), where_sql, params)
    code_rows = fetch_group_rows(conn, "s.code", where_sql, params)
    code_action_rows = fetch_group_rows(conn, "s.code || ' / ' || s.action_hint", where_sql, params)
    outcome_rows = fetch_outcomes(conn, where_sql, params)
    recent_rows = fetch_recent(conn, where_sql, params, limit=recent_limit)
    cluster_rows = build_cluster_rows(
        fetch_cluster_source_rows(conn, where_sql, params),
        window_minutes=DEFAULT_CLUSTER_WINDOW_MINUTES,
    )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "filters": {
            "code": code,
            "days": days,
            "min_sample": min_sample,
        },
        "sample_summary": sample_summary(row_to_dict(overview), min_sample=min_sample),
        "overview": row_to_dict(overview),
        "by_action": annotate_rows(action_rows, min_sample=min_sample),
        "by_decision_side": annotate_rows(decision_side_rows, min_sample=min_sample),
        "by_code": annotate_rows(code_rows, min_sample=min_sample),
        "by_code_action": annotate_rows(code_action_rows, min_sample=min_sample),
        "cluster_summary": cluster_metric_block(cluster_rows),
        "cluster_by_action": cluster_group_blocks(cluster_rows, "action_hint"),
        "outcomes": [row_to_dict(row) for row in outcome_rows],
        "recent_evaluated": [row_to_dict(row) for row in recent_rows],
    }


def make_where_clause(code=None, days=None):
    clauses = []
    params = []

    if code:
        clauses.append("s.code = ?")
        params.append(code)

    if days:
        since = datetime.now() - timedelta(days=days)
        clauses.append("s.detected_at >= ?")
        params.append(since.strftime("%Y-%m-%d %H:%M:%S.%f"))

    if not clauses:
        return "", params

    return "WHERE " + " AND ".join(clauses), params


def fetch_overview(conn, where_sql, params):
    sql = """
        SELECT
            COUNT(1) AS signal_count,
            COALESCE(SUM(CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_count,
            COALESCE(SUM(CASE WHEN r.return_5m_pct IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_5m_count,
            COALESCE(SUM(CASE WHEN r.return_10m_pct IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_10m_count,
            COALESCE(SUM(CASE WHEN r.return_30m_pct IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_30m_count,
            COALESCE(SUM(CASE WHEN r.return_60m_pct IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_60m_count,
            COALESCE(SUM(CASE WHEN r.id IS NOT NULL AND r.return_60m_pct IS NULL THEN 1 ELSE 0 END), 0) AS partial_evaluated_count,
            COALESCE(SUM(CASE WHEN r.id IS NULL THEN 1 ELSE 0 END), 0) AS pending_count,
            MIN(s.detected_at) AS first_signal_at,
            MAX(s.detected_at) AS latest_signal_at,
            MIN(r.evaluated_at) AS first_evaluated_at,
            MAX(r.evaluated_at) AS latest_evaluated_at,
            ROUND(AVG(r.return_5m_pct), 3) AS avg_return_5m_pct,
            ROUND(AVG(r.return_10m_pct), 3) AS avg_return_10m_pct,
            ROUND(AVG(r.return_30m_pct), 3) AS avg_return_30m_pct,
            ROUND(AVG(r.return_60m_pct), 3) AS avg_return_60m_pct,
            ROUND(AVG(r.return_30m_pct - {cost}), 3) AS avg_net_return_30m_pct,
            ROUND(AVG(r.return_60m_pct - {cost}), 3) AS avg_net_return_60m_pct,
            {win30} AS win_rate_30m_pct,
            {win60} AS win_rate_60m_pct,
            {net_win60} AS net_win_rate_60m_pct,
            {directional30} AS directional_success_30m_pct,
            {directional60} AS directional_success_60m_pct,
            {target1} AS target_1_hit_rate_pct,
            {target2} AS target_2_hit_rate_pct,
            {stop} AS stop_loss_hit_rate_pct
        FROM signal_logs s
        LEFT JOIN paper_trade_results r
            ON r.signal_id = s.id
        {where_sql}
    """.format(
        win30=rate_sql("r.return_30m_pct > 0", "r.return_30m_pct IS NOT NULL"),
        win60=rate_sql("r.return_60m_pct > 0", "r.return_60m_pct IS NOT NULL"),
        net_win60=rate_sql(
            "r.return_60m_pct > {cost}".format(cost=ROUND_TRIP_COST_PCT),
            "r.return_60m_pct IS NOT NULL"
        ),
        directional30=directional_success_rate_sql("r.return_30m_pct"),
        directional60=directional_success_rate_sql("r.return_60m_pct"),
        target1=rate_sql("r.target_1_hit = 1", "r.target_1_hit IS NOT NULL"),
        target2=rate_sql("r.target_2_hit = 1", "r.target_2_hit IS NOT NULL"),
        stop=rate_sql("r.stop_loss_hit = 1", "r.stop_loss_hit IS NOT NULL"),
        cost=ROUND_TRIP_COST_PCT,
        where_sql=where_sql,
    )
    return conn.execute(sql, params).fetchone()


def fetch_group_rows(conn, group_expr, where_sql, params):
    sql = """
        SELECT
            {group_expr} AS group_name,
            COUNT(1) AS signal_count,
            COALESCE(SUM(CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_count,
            COALESCE(SUM(CASE WHEN r.return_5m_pct IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_5m_count,
            COALESCE(SUM(CASE WHEN r.return_10m_pct IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_10m_count,
            COALESCE(SUM(CASE WHEN r.return_30m_pct IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_30m_count,
            COALESCE(SUM(CASE WHEN r.return_60m_pct IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_60m_count,
            COALESCE(SUM(CASE WHEN r.id IS NOT NULL AND r.return_60m_pct IS NULL THEN 1 ELSE 0 END), 0) AS partial_evaluated_count,
            COALESCE(SUM(CASE WHEN r.id IS NULL THEN 1 ELSE 0 END), 0) AS pending_count,
            ROUND(AVG(s.confidence_score), 2) AS avg_confidence_score,
            ROUND(AVG(r.return_5m_pct), 3) AS avg_return_5m_pct,
            ROUND(AVG(r.return_10m_pct), 3) AS avg_return_10m_pct,
            ROUND(AVG(r.return_30m_pct), 3) AS avg_return_30m_pct,
            ROUND(AVG(r.return_60m_pct), 3) AS avg_return_60m_pct,
            ROUND(AVG(r.return_30m_pct - {cost}), 3) AS avg_net_return_30m_pct,
            ROUND(AVG(r.return_60m_pct - {cost}), 3) AS avg_net_return_60m_pct,
            ROUND(AVG(r.max_gain_60m_pct), 3) AS avg_max_gain_60m_pct,
            ROUND(AVG(r.max_loss_60m_pct), 3) AS avg_max_loss_60m_pct,
            {win30} AS win_rate_30m_pct,
            {win60} AS win_rate_60m_pct,
            {net_win60} AS net_win_rate_60m_pct,
            {directional30} AS directional_success_30m_pct,
            {directional60} AS directional_success_60m_pct,
            {target1} AS target_1_hit_rate_pct,
            {target2} AS target_2_hit_rate_pct,
            {stop} AS stop_loss_hit_rate_pct
        FROM signal_logs s
        LEFT JOIN paper_trade_results r
            ON r.signal_id = s.id
        {where_sql}
        GROUP BY {group_expr}
        ORDER BY evaluated_count DESC, directional_success_60m_pct DESC, avg_return_60m_pct DESC
    """.format(
        group_expr=group_expr,
        win30=rate_sql("r.return_30m_pct > 0", "r.return_30m_pct IS NOT NULL"),
        win60=rate_sql("r.return_60m_pct > 0", "r.return_60m_pct IS NOT NULL"),
        net_win60=rate_sql(
            "r.return_60m_pct > {cost}".format(cost=ROUND_TRIP_COST_PCT),
            "r.return_60m_pct IS NOT NULL"
        ),
        directional30=directional_success_rate_sql("r.return_30m_pct"),
        directional60=directional_success_rate_sql("r.return_60m_pct"),
        target1=rate_sql("r.target_1_hit = 1", "r.target_1_hit IS NOT NULL"),
        target2=rate_sql("r.target_2_hit = 1", "r.target_2_hit IS NOT NULL"),
        stop=rate_sql("r.stop_loss_hit = 1", "r.stop_loss_hit IS NOT NULL"),
        cost=ROUND_TRIP_COST_PCT,
        where_sql=where_sql,
    )
    return conn.execute(sql, params).fetchall()


def fetch_outcomes(conn, where_sql, params):
    sql = """
        SELECT
            COALESCE(r.outcome_label, 'not_evaluated') AS outcome_label,
            COUNT(1) AS count
        FROM signal_logs s
        LEFT JOIN paper_trade_results r
            ON r.signal_id = s.id
        {where_sql}
        GROUP BY COALESCE(r.outcome_label, 'not_evaluated')
        ORDER BY count DESC
    """.format(where_sql=where_sql)
    return conn.execute(sql, params).fetchall()


def fetch_recent(conn, where_sql, params, limit):
    sql = """
        SELECT
            s.detected_at,
            s.code,
            s.name,
            s.action_hint,
            s.confidence_score,
            s.risk_level,
            r.return_5m_pct,
            r.return_10m_pct,
            r.return_30m_pct,
            r.return_60m_pct,
            r.max_gain_60m_pct,
            r.max_loss_60m_pct,
            r.target_1_hit,
            r.target_2_hit,
            r.stop_loss_hit,
            r.outcome_label
        FROM signal_logs s
        JOIN paper_trade_results r
            ON r.signal_id = s.id
        {where_sql}
        ORDER BY s.detected_at DESC
        LIMIT ?
    """.format(where_sql=where_sql)
    return conn.execute(sql, params + [limit]).fetchall()


def fetch_cluster_source_rows(conn, where_sql, params):
    sql = """
        SELECT
            s.id AS signal_id,
            s.detected_at,
            s.code,
            s.action_hint,
            r.id AS result_id,
            r.return_30m_pct,
            r.return_60m_pct,
            r.stop_loss_hit
        FROM signal_logs s
        LEFT JOIN paper_trade_results r
            ON r.signal_id = s.id
        {where_sql}
        ORDER BY s.code ASC, s.action_hint ASC, s.detected_at ASC
    """.format(where_sql=where_sql)
    return conn.execute(sql, params).fetchall()


def build_cluster_rows(rows, window_minutes=DEFAULT_CLUSTER_WINDOW_MINUTES):
    """Derive representative signal clusters without changing the DB schema."""
    clusters = []
    active = {}
    window_delta = timedelta(minutes=window_minutes)

    for row in rows:
        item = row_to_dict(row)
        detected_at = parse_dt(item.get("detected_at"))
        if not detected_at:
            continue
        key = (item.get("code"), item.get("action_hint"))
        current = active.get(key)
        if current is None or detected_at - current["cluster_started_at_dt"] > window_delta:
            current = {
                "cluster_id": "{}|{}|{}".format(
                    item.get("code"),
                    item.get("action_hint"),
                    item.get("detected_at"),
                ),
                "cluster_started_at": item.get("detected_at"),
                "cluster_started_at_dt": detected_at,
                "code": item.get("code"),
                "action_hint": item.get("action_hint"),
                "signals": [],
            }
            active[key] = current
            clusters.append(current)
        current["signals"].append(item)

    representative_rows = []
    for cluster in clusters:
        representative = first_evaluated_signal(cluster["signals"]) or cluster["signals"][0]
        representative_rows.append({
            "cluster_id": cluster["cluster_id"],
            "cluster_started_at": cluster["cluster_started_at"],
            "code": cluster["code"],
            "action_hint": cluster["action_hint"],
            "signal_count": len(cluster["signals"]),
            "result_id": representative.get("result_id"),
            "return_30m_pct": representative.get("return_30m_pct"),
            "return_60m_pct": representative.get("return_60m_pct"),
            "stop_loss_hit": representative.get("stop_loss_hit"),
        })
    return representative_rows


def first_evaluated_signal(rows):
    for row in rows:
        if row.get("return_60m_pct") is not None:
            return row
    for row in rows:
        if row.get("result_id") is not None:
            return row
    return None


def cluster_group_blocks(cluster_rows, key):
    groups = {}
    for row in cluster_rows:
        groups.setdefault(row.get(key) or "UNKNOWN", []).append(row)
    rows = []
    for group_name, group_rows in sorted(groups.items()):
        block = cluster_metric_block(group_rows)
        block["group_name"] = group_name
        rows.append(block)
    rows.sort(key=lambda item: (item.get("evaluated_cluster_count") or 0), reverse=True)
    return rows


def cluster_metric_block(cluster_rows):
    return_30m = [float(row["return_30m_pct"]) for row in cluster_rows if row.get("return_30m_pct") is not None]
    return_60m = [float(row["return_60m_pct"]) for row in cluster_rows if row.get("return_60m_pct") is not None]
    evaluated = [row for row in cluster_rows if row.get("result_id") is not None]
    return {
        "cluster_window_minutes": DEFAULT_CLUSTER_WINDOW_MINUTES,
        "cluster_count": len(cluster_rows),
        "evaluated_cluster_count": len(evaluated),
        "evaluated_cluster_60m_count": len(return_60m),
        "avg_cluster_return_30m_pct": average(return_30m),
        "avg_cluster_return_60m_pct": average(return_60m),
        "avg_cluster_net_return_60m_pct": average([value - ROUND_TRIP_COST_PCT for value in return_60m]),
        "cluster_win_rate_60m_pct": win_rate(return_60m),
        "cluster_net_win_rate_60m_pct": win_rate([value - ROUND_TRIP_COST_PCT for value in return_60m]),
        "cluster_profit_factor_60m": profit_factor(return_60m),
        "cluster_stop_loss_hit_rate_pct": rate(
            [row.get("stop_loss_hit") for row in evaluated if row.get("stop_loss_hit") is not None]
        ),
    }


def rate_sql(true_condition, denominator_condition):
    return (
        "ROUND(AVG(CASE WHEN {denominator} AND {true_condition} THEN 1.0 "
        "WHEN {denominator} THEN 0.0 END) * 100, 2)"
    ).format(true_condition=true_condition, denominator=denominator_condition)


def directional_success_rate_sql(return_column):
    denominator = (
        "{return_column} IS NOT NULL "
        "AND s.action_hint IN ({all_actions})"
    ).format(
        return_column=return_column,
        all_actions=sql_in_list(LONG_ACTIONS + CAUTION_ACTIONS),
    )
    success = (
        "(s.action_hint IN ({long_actions}) AND {return_column} > 0) "
        "OR (s.action_hint IN ({caution_actions}) AND {return_column} <= 0)"
    ).format(
        long_actions=sql_in_list(LONG_ACTIONS),
        caution_actions=sql_in_list(CAUTION_ACTIONS),
        return_column=return_column,
    )
    return (
        "ROUND(AVG(CASE WHEN {denominator} AND ({success}) THEN 1.0 "
        "WHEN {denominator} THEN 0.0 END) * 100, 2)"
    ).format(denominator=denominator, success=success)


def decision_side_expr():
    return (
        "CASE "
        "WHEN s.action_hint IN ({long_actions}) THEN 'long_candidate' "
        "WHEN s.action_hint IN ({caution_actions}) THEN 'caution_or_avoid' "
        "ELSE 'unknown' END"
    ).format(
        long_actions=sql_in_list(LONG_ACTIONS),
        caution_actions=sql_in_list(CAUTION_ACTIONS),
    )


def sql_in_list(values):
    return ",".join("'{}'".format(value.replace("'", "''")) for value in values)


def annotate_rows(rows, min_sample):
    annotated = []
    for row in rows:
        item = row_to_dict(row)
        item["sample_label"] = sample_label(item, min_sample=min_sample)
        item["profit_label"] = profit_label(item, min_sample=min_sample)
        item["directional_label"] = directional_label(item, min_sample=min_sample)
        item["interpretation_hint"] = interpretation_hint(item)
        item["quality_label"] = quality_label(item, min_sample=min_sample)
        item["tuning_hint"] = tuning_hint(item)
        annotated.append(item)
    return annotated


def sample_summary(overview, min_sample):
    evaluated = overview.get("evaluated_count") or 0
    evaluated_60m = overview.get("evaluated_60m_count") or 0
    partial = overview.get("partial_evaluated_count") or 0
    pending = overview.get("pending_count") or 0
    return {
        "sample_label": sample_label(overview, min_sample=min_sample),
        "evaluated_count": evaluated,
        "evaluated_60m_count": evaluated_60m,
        "partial_evaluated_count": partial,
        "pending_count": pending,
        "full_60m_ratio_pct": round((evaluated_60m / evaluated) * 100, 2) if evaluated else None,
        "headline_rule": "Use 60m return headlines only from evaluated_60m_count; keep partial and pending counts separate.",
    }


def sample_label(row, min_sample):
    evaluated = row.get("evaluated_count") or 0
    evaluated_60m = row.get("evaluated_60m_count") or 0
    partial = row.get("partial_evaluated_count") or 0
    pending = row.get("pending_count") or 0

    if evaluated_60m < min_sample:
        return "sample_insufficient_60m"
    if partial or pending:
        return "mixed_full_partial_or_pending"
    if evaluated and evaluated == evaluated_60m:
        return "full_60m_sample"
    return "evaluated_60m_sample"


def profit_label(row, min_sample):
    evaluated = row.get("evaluated_60m_count") or 0
    net_avg_60m = row.get("avg_net_return_60m_pct")
    stop_hit = row.get("stop_loss_hit_rate_pct")

    if evaluated < min_sample:
        return "sample_insufficient"
    if stop_hit is not None and stop_hit >= 60:
        return "high_stop_risk"
    if net_avg_60m is None:
        return "profit_unknown"
    if net_avg_60m > 0:
        return "positive_net_expectancy"
    if net_avg_60m < 0:
        return "negative_net_expectancy"
    return "flat_net_expectancy"


def directional_label(row, min_sample):
    evaluated = row.get("evaluated_60m_count") or 0
    directional_60m = row.get("directional_success_60m_pct")

    if evaluated < min_sample:
        return "sample_insufficient"
    if directional_60m is None:
        return "direction_unknown"
    if directional_60m >= 60:
        return "direction_validated"
    if directional_60m < 40:
        return "direction_contra"
    return "direction_neutral"


def action_side(group_name):
    if not group_name:
        return "unknown"
    action = str(group_name).split("/")[-1].strip()
    if action in LONG_ACTIONS:
        return "long_candidate"
    if action in CAUTION_ACTIONS:
        return "caution_or_avoid"
    if group_name in ("long_candidate", "caution_or_avoid"):
        return group_name
    return "unknown"


def interpretation_hint(row):
    side = action_side(row.get("group_name"))
    profit = row.get("profit_label")
    direction = row.get("directional_label")

    if side == "caution_or_avoid" and profit == "positive_net_expectancy" and direction == "direction_contra":
        return "caution_missed_upside"
    if side == "caution_or_avoid" and profit == "negative_net_expectancy" and direction == "direction_validated":
        return "caution_worked"
    if side == "long_candidate" and profit == "positive_net_expectancy" and direction == "direction_validated":
        return "long_signal_worked"
    if side == "long_candidate" and profit == "negative_net_expectancy":
        return "long_signal_failed"
    return "mixed_or_neutral"


def quality_label(row, min_sample):
    evaluated = row.get("evaluated_60m_count") or 0
    directional_60m = row.get("directional_success_60m_pct")
    net_avg_60m = row.get("avg_net_return_60m_pct")
    stop_hit = row.get("stop_loss_hit_rate_pct")

    if evaluated < min_sample:
        return "sample_insufficient"

    if directional_60m is not None and directional_60m >= 60:
        return "direction_validated"

    if directional_60m is not None and directional_60m < 40:
        return "direction_degraded"

    if net_avg_60m is not None and net_avg_60m > 0 and (stop_hit is None or stop_hit <= 45):
        return "profit_validated"

    if net_avg_60m is not None and net_avg_60m < 0:
        return "profit_degraded"

    if stop_hit is not None and stop_hit >= 60:
        return "stop_risk"

    return "neutral"


def tuning_hint(row):
    label = row.get("quality_label")
    if label in ("direction_validated", "profit_validated"):
        return "raise_confidence_only_when_live_setup_matches"
    if label in ("direction_degraded", "profit_degraded"):
        return "tighten_threshold_or_require_extra_confirmation"
    if label == "stop_risk":
        return "recheck_stop_target_or_entry_condition"
    if label == "sample_insufficient":
        return "collect_more_intraday_samples"
    return "keep_current_threshold_and_collect_more_samples"


def row_to_dict(row):
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def average(values):
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def win_rate(values):
    if not values:
        return None
    return round(len([value for value in values if value > 0]) / len(values) * 100, 2)


def profit_factor(values):
    if not values:
        return None
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses == 0:
        return 999.0 if gains > 0 else None
    return round(gains / losses, 4)


def rate(values):
    if not values:
        return None
    return round(len([value for value in values if int(value) == 1]) / len(values) * 100, 2)


def print_text_report(report):
    overview = report["overview"]
    filters = report["filters"]

    print("========== Paper Trade Quality Report ==========")
    print("generated_at:", report["generated_at"])
    print("filters: code={code}, days={days}, min_sample={min_sample}".format(**filters))
    print()

    print("[Overview]")
    sample = report.get("sample_summary", {})
    print(
        "signals={signals}, evaluated={evaluated}, pending={pending}, partial={partial}, "
        "eval_5/10/30/60m={eval5}/{eval10}/{eval30}/{eval60}, "
        "cost={cost}, avg_30m={avg30}, avg_60m={avg60}, "
        "net_avg_30m={net30}, net_avg_60m={net60}, win_60m={win60}, net_win_60m={netwin60}, "
        "directional_60m={directional60}, stop_hit={stop}"
        .format(
            signals=overview.get("signal_count"),
            evaluated=overview.get("evaluated_count"),
            pending=overview.get("pending_count"),
            partial=overview.get("partial_evaluated_count"),
            eval5=overview.get("evaluated_5m_count"),
            eval10=overview.get("evaluated_10m_count"),
            eval30=overview.get("evaluated_30m_count"),
            eval60=overview.get("evaluated_60m_count"),
            cost=round(ROUND_TRIP_COST_PCT, 4),
            avg30=overview.get("avg_return_30m_pct"),
            avg60=overview.get("avg_return_60m_pct"),
            net30=overview.get("avg_net_return_30m_pct"),
            net60=overview.get("avg_net_return_60m_pct"),
            win60=overview.get("win_rate_60m_pct"),
            netwin60=overview.get("net_win_rate_60m_pct"),
            directional60=overview.get("directional_success_60m_pct"),
            stop=overview.get("stop_loss_hit_rate_pct"),
        )
    )
    print(
        "sample_label={label}, full_60m_ratio={ratio}, headline_rule={rule}"
        .format(
            label=sample.get("sample_label"),
            ratio=sample.get("full_60m_ratio_pct"),
            rule=sample.get("headline_rule"),
        )
    )
    print("first_signal:", overview.get("first_signal_at"))
    print("latest_signal:", overview.get("latest_signal_at"))
    print()

    cluster = report.get("cluster_summary") or {}
    print("[Cluster Summary]")
    print(
        "window={window}m, clusters={clusters}, evaluated_clusters={evaluated}, "
        "eval60={eval60}, avg60={avg60}, net60={net60}, win60={win60}, "
        "netwin60={netwin60}, pf60={pf60}, stop={stop}"
        .format(
            window=cluster.get("cluster_window_minutes"),
            clusters=cluster.get("cluster_count"),
            evaluated=cluster.get("evaluated_cluster_count"),
            eval60=cluster.get("evaluated_cluster_60m_count"),
            avg60=cluster.get("avg_cluster_return_60m_pct"),
            net60=cluster.get("avg_cluster_net_return_60m_pct"),
            win60=cluster.get("cluster_win_rate_60m_pct"),
            netwin60=cluster.get("cluster_net_win_rate_60m_pct"),
            pf60=cluster.get("cluster_profit_factor_60m"),
            stop=cluster.get("cluster_stop_loss_hit_rate_pct"),
        )
    )
    print()

    print("[By Action]")
    print_group_rows(report["by_action"])
    print()

    print("[By Decision Side]")
    print_group_rows(report["by_decision_side"])
    print()

    print("[By Code]")
    print_group_rows(report["by_code"])
    print()

    print("[By Code / Action]")
    print_group_rows(report["by_code_action"])
    print()

    print("[Outcomes]")
    for item in report["outcomes"]:
        print("  {label}: {count}".format(
            label=item.get("outcome_label"),
            count=item.get("count"),
        ))
    print()

    print("[Recent Evaluated]")
    for item in report["recent_evaluated"]:
        print(
            "  {time} {code} {action} ret30={ret30} ret60={ret60} "
            "max60={max60}/{min60} outcome={outcome}"
            .format(
                time=item.get("detected_at"),
                code=item.get("code"),
                action=item.get("action_hint"),
                ret30=item.get("return_30m_pct"),
                ret60=item.get("return_60m_pct"),
                max60=item.get("max_gain_60m_pct"),
                min60=item.get("max_loss_60m_pct"),
                outcome=item.get("outcome_label"),
            )
        )


def print_window_comparison(report):
    print("========== Paper Trade Window Comparison ==========")
    print("generated_at:", report.get("generated_at"))
    print("filters:", report.get("filters"))
    print()

    for item in report.get("windows") or []:
        overview = item.get("overview") or {}
        sample = item.get("sample_summary") or {}
        long_row = item.get("long_candidate") or {}
        caution_row = item.get("caution_or_avoid") or {}
        print("[{} days]".format(item.get("days")))
        print(
            "signals={signals}, eval60={eval60}, pending={pending}, "
            "net60={net60}, netwin60={netwin}, directional60={directional}, "
            "stop={stop}, full60={full60}"
            .format(
                signals=overview.get("signal_count"),
                eval60=overview.get("evaluated_60m_count"),
                pending=overview.get("pending_count"),
                net60=overview.get("avg_net_return_60m_pct"),
                netwin=overview.get("net_win_rate_60m_pct"),
                directional=overview.get("directional_success_60m_pct"),
                stop=overview.get("stop_loss_hit_rate_pct"),
                full60=sample.get("full_60m_ratio_pct"),
            )
        )
        print(
            "  long: eval60={eval60}, net60={net60}, directional={directional}, label={label}, hint={hint}"
            .format(
                eval60=long_row.get("evaluated_60m_count"),
                net60=long_row.get("avg_net_return_60m_pct"),
                directional=long_row.get("directional_success_60m_pct"),
                label=long_row.get("quality_label"),
                hint=long_row.get("tuning_hint"),
            )
        )
        print(
            "  caution: eval60={eval60}, net60={net60}, directional={directional}, label={label}, hint={hint}"
            .format(
                eval60=caution_row.get("evaluated_60m_count"),
                net60=caution_row.get("avg_net_return_60m_pct"),
                directional=caution_row.get("directional_success_60m_pct"),
                label=caution_row.get("quality_label"),
                hint=caution_row.get("tuning_hint"),
            )
        )
        print("  best_actions:")
        for row in item.get("best_actions") or []:
            print("    {name}: eval60={eval60}, net60={net60}, direction={direction}, quality={quality}".format(
                name=row.get("group_name"),
                eval60=row.get("evaluated_60m_count"),
                net60=row.get("avg_net_return_60m_pct"),
                direction=row.get("directional_success_60m_pct"),
                quality=row.get("quality_label"),
            ))
        print("  weakest_code_actions:")
        for row in item.get("weakest_code_actions") or []:
            print("    {name}: eval60={eval60}, net60={net60}, direction={direction}, quality={quality}".format(
                name=row.get("group_name"),
                eval60=row.get("evaluated_60m_count"),
                net60=row.get("avg_net_return_60m_pct"),
                direction=row.get("directional_success_60m_pct"),
                quality=row.get("quality_label"),
            ))
        print()


def print_group_rows(rows):
    if not rows:
        print("  no rows")
        return

    for item in rows:
        print(
            "  {name}: signals={signals}, eval={evaluated}, eval60={eval60}, partial={partial}, "
            "avg60={avg60}, net60={net60}, win60={win60}, netwin60={netwin60}, "
            "directional60={directional60}, stop={stop}, "
            "profit={profit}, direction={direction}, sample={sample}, "
            "interpretation={interpretation}, label={label}, hint={hint}"
            .format(
                name=item.get("group_name"),
                signals=item.get("signal_count"),
                evaluated=item.get("evaluated_count"),
                eval60=item.get("evaluated_60m_count"),
                partial=item.get("partial_evaluated_count"),
                avg60=item.get("avg_return_60m_pct"),
                net60=item.get("avg_net_return_60m_pct"),
                win60=item.get("win_rate_60m_pct"),
                netwin60=item.get("net_win_rate_60m_pct"),
                directional60=item.get("directional_success_60m_pct"),
                stop=item.get("stop_loss_hit_rate_pct"),
                profit=item.get("profit_label"),
                direction=item.get("directional_label"),
                sample=item.get("sample_label"),
                interpretation=item.get("interpretation_hint"),
                label=item.get("quality_label"),
                hint=item.get("tuning_hint"),
            )
        )


if __name__ == "__main__":
    main()
