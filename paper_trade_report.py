"""Paper-trade performance report for saved validation signals.

This is a quality-control tool. It answers two separate questions:
- Did long-candidate signals make money after the signal?
- Did avoid/caution signals correctly warn against weak follow-through?
"""

import argparse
import json
from datetime import datetime, timedelta

from app_paths import DEFAULT_DB_PATH
from data_store import TickStore


LONG_ACTIONS = (
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


def main():
    args = parse_args()
    store = TickStore(db_path=args.db)

    try:
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
    else:
        print_text_report(report)


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize paper-trade performance from SQLite.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--code", help="Optional stock code filter")
    parser.add_argument("--days", type=int, help="Only include signals from the latest N days")
    parser.add_argument("--min-sample", type=int, default=5, help="Minimum evaluated rows before a label is trusted")
    parser.add_argument("--recent-limit", type=int, default=10, help="Recent evaluated signals to print")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    return parser.parse_args()


def build_report(conn, code=None, days=None, min_sample=5, recent_limit=10):
    where_sql, params = make_where_clause(code=code, days=days)

    overview = fetch_overview(conn, where_sql, params)
    action_rows = fetch_group_rows(conn, "s.action_hint", where_sql, params)
    code_rows = fetch_group_rows(conn, "s.code", where_sql, params)
    code_action_rows = fetch_group_rows(conn, "s.code || ' / ' || s.action_hint", where_sql, params)
    outcome_rows = fetch_outcomes(conn, where_sql, params)
    recent_rows = fetch_recent(conn, where_sql, params, limit=recent_limit)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "filters": {
            "code": code,
            "days": days,
            "min_sample": min_sample,
        },
        "overview": row_to_dict(overview),
        "by_action": annotate_rows(action_rows, min_sample=min_sample),
        "by_code": annotate_rows(code_rows, min_sample=min_sample),
        "by_code_action": annotate_rows(code_action_rows, min_sample=min_sample),
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
            {win30} AS win_rate_30m_pct,
            {win60} AS win_rate_60m_pct,
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
        directional30=directional_success_rate_sql("r.return_30m_pct"),
        directional60=directional_success_rate_sql("r.return_60m_pct"),
        target1=rate_sql("r.target_1_hit = 1", "r.target_1_hit IS NOT NULL"),
        target2=rate_sql("r.target_2_hit = 1", "r.target_2_hit IS NOT NULL"),
        stop=rate_sql("r.stop_loss_hit = 1", "r.stop_loss_hit IS NOT NULL"),
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
            ROUND(AVG(r.max_gain_60m_pct), 3) AS avg_max_gain_60m_pct,
            ROUND(AVG(r.max_loss_60m_pct), 3) AS avg_max_loss_60m_pct,
            {win30} AS win_rate_30m_pct,
            {win60} AS win_rate_60m_pct,
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
        directional30=directional_success_rate_sql("r.return_30m_pct"),
        directional60=directional_success_rate_sql("r.return_60m_pct"),
        target1=rate_sql("r.target_1_hit = 1", "r.target_1_hit IS NOT NULL"),
        target2=rate_sql("r.target_2_hit = 1", "r.target_2_hit IS NOT NULL"),
        stop=rate_sql("r.stop_loss_hit = 1", "r.stop_loss_hit IS NOT NULL"),
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


def sql_in_list(values):
    return ",".join("'{}'".format(value.replace("'", "''")) for value in values)


def annotate_rows(rows, min_sample):
    annotated = []
    for row in rows:
        item = row_to_dict(row)
        item["quality_label"] = quality_label(item, min_sample=min_sample)
        item["tuning_hint"] = tuning_hint(item)
        annotated.append(item)
    return annotated


def quality_label(row, min_sample):
    evaluated = row.get("evaluated_60m_count") or 0
    directional_60m = row.get("directional_success_60m_pct")
    avg_60m = row.get("avg_return_60m_pct")
    stop_hit = row.get("stop_loss_hit_rate_pct")

    if evaluated < min_sample:
        return "표본부족"

    if directional_60m is not None and directional_60m >= 60:
        return "판단우수"

    if directional_60m is not None and directional_60m < 40:
        return "판단하향검토"

    if avg_60m is not None and avg_60m > 0 and (stop_hit is None or stop_hit <= 45):
        return "수익우수"

    if avg_60m is not None and avg_60m < 0:
        return "수익하향검토"

    if stop_hit is not None and stop_hit >= 60:
        return "손절위험"

    return "중립"


def tuning_hint(row):
    label = row.get("quality_label")
    if label in ("판단우수", "수익우수"):
        return "유사 조건에서 신뢰도 상향 후보"
    if label in ("판단하향검토", "수익하향검토"):
        return "임계값 강화 또는 추가 확인 필요"
    if label == "손절위험":
        return "손절/목표가 산식 또는 진입 조건 재검토"
    if label == "표본부족":
        return "추가 장중 데이터 필요"
    return "현상 유지 후 표본 추가"


def row_to_dict(row):
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def print_text_report(report):
    overview = report["overview"]
    filters = report["filters"]

    print("========== Paper Trade Quality Report ==========")
    print("generated_at:", report["generated_at"])
    print("filters: code={code}, days={days}, min_sample={min_sample}".format(**filters))
    print()

    print("[Overview]")
    print(
        "signals={signals}, evaluated={evaluated}, pending={pending}, partial={partial}, "
        "eval_5/10/30/60m={eval5}/{eval10}/{eval30}/{eval60}, "
        "avg_30m={avg30}, avg_60m={avg60}, win_60m={win60}, "
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
            avg30=overview.get("avg_return_30m_pct"),
            avg60=overview.get("avg_return_60m_pct"),
            win60=overview.get("win_rate_60m_pct"),
            directional60=overview.get("directional_success_60m_pct"),
            stop=overview.get("stop_loss_hit_rate_pct"),
        )
    )
    print("first_signal:", overview.get("first_signal_at"))
    print("latest_signal:", overview.get("latest_signal_at"))
    print()

    print("[By Action]")
    print_group_rows(report["by_action"])
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


def print_group_rows(rows):
    if not rows:
        print("  no rows")
        return

    for item in rows:
        print(
            "  {name}: signals={signals}, eval={evaluated}, eval60={eval60}, partial={partial}, avg60={avg60}, "
            "win60={win60}, directional60={directional60}, stop={stop}, "
            "label={label}, hint={hint}"
            .format(
                name=item.get("group_name"),
                signals=item.get("signal_count"),
                evaluated=item.get("evaluated_count"),
                eval60=item.get("evaluated_60m_count"),
                partial=item.get("partial_evaluated_count"),
                avg60=item.get("avg_return_60m_pct"),
                win60=item.get("win_rate_60m_pct"),
                directional60=item.get("directional_success_60m_pct"),
                stop=item.get("stop_loss_hit_rate_pct"),
                label=item.get("quality_label"),
                hint=item.get("tuning_hint"),
            )
        )


if __name__ == "__main__":
    main()
