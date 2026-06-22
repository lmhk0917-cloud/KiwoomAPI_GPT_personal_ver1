"""Compare deterministic quant scores, GPT scores, and paper outcomes."""

import argparse
import json
from datetime import datetime, timedelta

from app_paths import DEFAULT_DB_PATH
from config import TRADE_BUY_FEE_PCT, TRADE_SELL_FEE_PCT, TRADE_SELL_TAX_PCT, TRADE_SLIPPAGE_PCT
from data_store import TickStore
from target_exit_scenarios import build_target_exit_scenarios


ROUND_TRIP_COST_PCT = TRADE_BUY_FEE_PCT + TRADE_SELL_FEE_PCT + TRADE_SELL_TAX_PCT + (TRADE_SLIPPAGE_PCT * 2)
HORIZONS_MIN = (5, 10, 30, 60)


def main():
    args = parse_args()
    store = TickStore(db_path=args.db)
    try:
        report = build_report(store.conn, days=args.days, code=args.code, limit=args.limit)
    finally:
        store.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)


def parse_args():
    parser = argparse.ArgumentParser(description="Compare quant/GPT/paper score rows.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--code")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(conn, days=5, code=None, limit=20):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S.%f")
    params = [since]
    code_filter = ""
    if code:
        code_filter = "AND q.code = ?"
        params.append(code)

    overview = conn.execute("""
        SELECT
            COUNT(1) AS quant_count,
            ROUND(AVG(q.final_quant_score), 3) AS avg_final_quant_score,
            ROUND(AVG(q.expected_value_score), 3) AS avg_expected_value_score,
            ROUND(AVG(g.confidence), 3) AS avg_gpt_confidence,
            ROUND(AVG(g.risk_score), 3) AS avg_gpt_risk_score,
            ROUND(AVG(p.return_60m_pct), 3) AS avg_return_60m_pct,
            ROUND(AVG(p.return_60m_pct - {cost}), 3) AS avg_net_return_60m_pct,
            SUM(CASE WHEN p.return_60m_pct > 0 THEN 1 ELSE 0 END) AS positive_60m_count,
            SUM(CASE WHEN p.return_60m_pct IS NOT NULL THEN 1 ELSE 0 END) AS evaluated_60m_count
        FROM quant_signal_scores q
        LEFT JOIN paper_trade_results p
            ON p.signal_id = q.signal_id
        LEFT JOIN gpt_analysis_scores g
            ON g.code = q.code
           AND g.analyzed_at >= q.scored_at
           AND g.analyzed_at <= datetime(q.scored_at, '+5 minutes')
        WHERE q.scored_at >= ?
        {code_filter}
    """.format(code_filter=code_filter, cost=ROUND_TRIP_COST_PCT), params).fetchone()

    by_action = conn.execute("""
        SELECT
            q.action_hint,
            COUNT(1) AS quant_count,
            ROUND(AVG(q.final_quant_score), 3) AS avg_final_quant_score,
            ROUND(AVG(q.expected_value_score), 3) AS avg_expected_value_score,
            ROUND(AVG(q.market_risk_score), 3) AS avg_market_risk_score,
            ROUND(AVG(p.return_60m_pct), 3) AS avg_return_60m_pct,
            ROUND(AVG(p.return_60m_pct - {cost}), 3) AS avg_net_return_60m_pct,
            SUM(CASE WHEN p.return_60m_pct > 0 THEN 1 ELSE 0 END) AS positive_60m_count,
            SUM(CASE WHEN p.return_60m_pct IS NOT NULL THEN 1 ELSE 0 END) AS evaluated_60m_count
        FROM quant_signal_scores q
        LEFT JOIN paper_trade_results p
            ON p.signal_id = q.signal_id
        WHERE q.scored_at >= ?
        {code_filter}
        GROUP BY q.action_hint
        ORDER BY quant_count DESC
    """.format(code_filter=code_filter, cost=ROUND_TRIP_COST_PCT), params).fetchall()

    horizon_summary = []
    for minutes in HORIZONS_MIN:
        column = "return_{}m_pct".format(minutes)
        horizon_row = conn.execute("""
            SELECT
                ? AS horizon_min,
                SUM(CASE WHEN p.{column} IS NOT NULL THEN 1 ELSE 0 END) AS evaluated_count,
                ROUND(AVG(p.{column}), 3) AS avg_return_pct,
                ROUND(AVG(p.{column} - ?), 3) AS avg_net_return_pct,
                ROUND(100.0 * SUM(CASE WHEN p.{column} > 0 THEN 1 ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN p.{column} IS NOT NULL THEN 1 ELSE 0 END), 0), 3) AS win_rate_pct,
                ROUND(MAX(p.{column}), 3) AS best_return_pct,
                ROUND(MIN(p.{column}), 3) AS worst_return_pct
            FROM quant_signal_scores q
            LEFT JOIN paper_trade_results p
                ON p.signal_id = q.signal_id
            WHERE q.scored_at >= ?
            {code_filter}
        """.format(column=column, code_filter=code_filter), [minutes, ROUND_TRIP_COST_PCT] + params).fetchone()
        horizon_summary.append(_row(horizon_row))

    recent_params = list(params)
    recent_params.append(limit)
    recent = conn.execute("""
        SELECT
            q.scored_at,
            q.code,
            q.action_hint,
            q.final_quant_score,
            q.expected_value_score,
            q.market_risk_score,
            g.decision AS gpt_decision,
            g.confidence AS gpt_confidence,
            g.risk_score AS gpt_risk_score,
            g.parse_status AS gpt_parse_status,
            p.return_30m_pct,
            p.return_60m_pct,
            p.outcome_label
        FROM quant_signal_scores q
        LEFT JOIN paper_trade_results p
            ON p.signal_id = q.signal_id
        LEFT JOIN gpt_analysis_scores g
            ON g.code = q.code
           AND g.analyzed_at >= q.scored_at
           AND g.analyzed_at <= datetime(q.scored_at, '+5 minutes')
        WHERE q.scored_at >= ?
        {code_filter}
        ORDER BY q.scored_at DESC, q.id DESC
        LIMIT ?
    """.format(code_filter=code_filter), recent_params).fetchall()

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "filters": {"days": days, "code": code},
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        "overview": _row(overview),
        "horizon_summary": horizon_summary,
        "target_exit_scenarios": build_target_exit_scenarios(conn, days=days, code=code),
        "by_action": [_row(row) for row in by_action],
        "recent": [_row(row) for row in recent],
    }


def print_text_report(report):
    print("========== Quant/GPT Score Report ==========")
    print("generated_at:", report.get("generated_at"))
    print("filters:", report.get("filters"))
    overview = report.get("overview") or {}
    print("[Overview]")
    print(", ".join("{}={}".format(key, value) for key, value in overview.items()))
    print("[Horizon Summary]")
    for row in report.get("horizon_summary") or []:
        print("  " + ", ".join("{}={}".format(key, value) for key, value in row.items()))
    print("[Target Exit Scenarios]")
    for row in report.get("target_exit_scenarios") or []:
        print("  " + ", ".join("{}={}".format(key, value) for key, value in row.items()))
    print("[By Action]")
    for row in report.get("by_action") or []:
        print("  " + ", ".join("{}={}".format(key, value) for key, value in row.items()))
    print("[Recent]")
    for row in report.get("recent") or []:
        print("  " + ", ".join("{}={}".format(key, value) for key, value in row.items()))


def _row(row):
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


if __name__ == "__main__":
    raise SystemExit(main())
