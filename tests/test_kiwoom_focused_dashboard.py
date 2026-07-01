import json
import os
import sys
import tempfile
import unittest

from kiwoom_focused_dashboard import (
    _readable_summary_text,
    build_dashboard_snapshot,
    load_symbols,
    render_dashboard_html,
    save_symbols,
)
from market_context import load_latest_shared_toss_context
from storage.schema import create_or_migrate_schema

import sqlite3


class KiwoomFocusedDashboardTests(unittest.TestCase):
    def test_watchlist_load_save_roundtrip(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        path = handle.name
        handle.close()
        try:
            saved = save_symbols(["005930", " 000660 ", "005930"], path)
            self.assertEqual(["005930", "000660"], saved)
            self.assertEqual(["005930", "000660"], load_symbols(path))
        finally:
            os.unlink(path)

    def test_shared_toss_context_loads_from_hub_without_toss_db(self):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        shared_db = handle.name
        handle.close()
        shared_root = r"C:\Users\lmhk2\Documents\New project\shared_market_context"
        if shared_root not in sys.path:
            sys.path.insert(0, shared_root)
        from shared_context_store import SharedContextStore

        store = SharedContextStore(db_path=shared_db)
        try:
            store.insert_snapshot(
                "toss",
                "GLOBAL",
                None,
                "relationship",
                "relationship_metrics",
                {
                    "relationship_regime": "insufficient_evidence",
                    "pairs": [],
                    "interpretation_rules": [
                        "Daily relationship rows are not intraday timing evidence.",
                    ],
                },
                collected_at="2026-06-26T22:00:00+09:00",
                sample_count=0,
                status="partial",
            )
        finally:
            store.close()

        try:
            context = load_latest_shared_toss_context(shared_db_path=shared_db)
            self.assertEqual("ok", context["status"])
            self.assertEqual("shared_context_db", context["source_preference"])
            self.assertIn("relationship_metrics", context["sections"])
            self.assertEqual(
                "insufficient_evidence",
                context["sections"]["relationship_metrics"][0]["payload"]["relationship_regime"],
            )
        finally:
            os.unlink(shared_db)

    def test_snapshot_and_html_render_from_minimal_db(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        db_path = handle.name
        handle.close()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            create_or_migrate_schema(conn)
            conn.execute("""
                INSERT INTO ticks (
                    code, trade_time, price, change_rate, acc_volume, tick_volume,
                    open_price, high_price, low_price, strength, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "005930", "090001", 70000, 0.5, 1000, 10,
                69800, 70100, 69700, 105.0, "2026-06-17 09:00:01.000000",
            ))
            conn.execute("""
                INSERT INTO signal_logs (
                    detected_at, code, name, action_hint, confidence_score,
                    risk_level, current_price, stop_loss, target_1, target_2,
                    reason_json, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-17 09:00:10.000000", "005930", "Samsung",
                "OBSERVE_EVENT", 55, "MEDIUM", 70000, 69000, 71000, 72000,
                "{}", "{}",
            ))
            conn.execute("""
                INSERT INTO analysis_results (
                    analyzed_at, code, name, current_price, rsi14, ma5, ma20,
                    ma60, volume_ratio_5, volume_ratio_20, vwap,
                    vwap_distance_pct, box_high, box_low, box_position,
                    day_open, day_high, day_low, strength, market_context_json,
                    summary_json, gpt_result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-17 09:01:00.000000", "005930", "Samsung", 70000,
                55, 69900, 69800, 69700, 1.2, 1.1, 69950, 0.07,
                70500, 69500, 50, 69800, 70100, 69700, 105.0,
                '{"macro_context":{"summary":"test"}}', '{"code":"005930"}',
                "GPT result",
            ))
            conn.execute("""
                INSERT INTO event_logs (
                    detected_at, code, name, event_type, timeframe, message,
                    value, gpt_requested, skip_reason, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-17 09:00:20.000000", "005930", "Samsung",
                "NEAR_VWAP_SUPPORT", "1m", "near vwap", 0.1, 1, None, "{}",
            ))
            conn.execute("""
                INSERT INTO paper_trade_results (
                    signal_id, evaluated_at, code, entry_time, entry_price,
                    return_5m_pct, return_10m_pct, return_30m_pct,
                    return_60m_pct, max_gain_30m_pct, max_loss_30m_pct,
                    max_gain_60m_pct, max_loss_60m_pct, target_1_hit,
                    target_2_hit, stop_loss_hit, outcome_label, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                1, "2026-06-17 10:00:00.000000", "005930",
                "2026-06-17 09:00:10.000000", 70000, 0.1, 0.2, 0.3,
                0.4, 0.5, -0.2, 0.7, -0.3, 0, 0, 0, "win", "{}",
            ))
            conn.execute("""
                INSERT INTO market_context_snapshots (
                    collected_at, scope, code, section, source, asof,
                    reliability, weight, summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-17 09:00:00.000000", "global", None,
                "macro_context", "manual", "2026-06-17 09:00:00",
                "manual", "high", "macro summary", "{}",
            ))
            conn.execute("""
                INSERT INTO market_context_snapshots (
                    collected_at, scope, code, section, source, asof,
                    reliability, weight, summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-17 09:02:00.000000", "global", None,
                "market_investor_flow", "OPT10051", "2026-06-17 09:02:00",
                "sector_sum_proxy_pending_live_unit_validation", "medium", "market flow",
                json.dumps({
                    "kospi_sector_count": 28,
                    "kospi_individual_net_value": 1200,
                    "kospi_foreign_net_value": -500,
                    "kospi_institution_net_value": -700,
                    "kosdaq_sector_count": 32,
                    "kosdaq_individual_net_value": 300,
                    "kosdaq_foreign_net_value": -100,
                    "kosdaq_institution_net_value": -200,
                    "combined_individual_net_value": 1500,
                    "combined_foreign_net_value": -600,
                    "combined_institution_net_value": -900,
                }),
            ))
            conn.execute("""
                INSERT INTO market_context_snapshots (
                    collected_at, scope, code, section, source, asof,
                    reliability, weight, summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-17 09:02:10.000000", "global", None,
                "market_program_trading", "OPT90005", "2026-06-17 09:02:10",
                "live", "medium", "program flow",
                json.dumps({"market": "KOSPI", "total_net_value": -12345}),
            ))
            conn.execute("""
                INSERT INTO market_context_snapshots (
                    collected_at, scope, code, section, source, asof,
                    reliability, weight, summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-17 09:02:20.000000", "code", "005930",
                "investor_flow", "OPT10059", "2026-06-17 09:02:20",
                "live", "medium", "symbol flow",
                json.dumps({
                    "individual_net_value": 10,
                    "foreign_net_value": -4,
                    "institution_net_value": -6,
                }),
            ))
            conn.execute("""
                INSERT INTO gpt_call_logs (
                    started_at, finished_at, status, requested_count, codes,
                    model, duration_ms, prompt_chars, payload_original_chars,
                    payload_compressed_chars, payload_compression_ratio,
                    prompt_tokens, completion_tokens, total_tokens,
                    error_message, result_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-17 09:01:00.000000", "2026-06-17 09:01:05.000000",
                "success", 1, "005930", "test", 5000, 100, 100, 80,
                0.8, 10, 20, 30, None, "ok",
            ))
            conn.execute("""
                INSERT INTO quant_signal_scores (
                    signal_id, scored_at, code, action_hint, quant_signal_score,
                    expected_value_score, market_risk_score, final_quant_score,
                    decision_side, feature_json, formula_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                1, "2026-06-22 09:00:10.000000", "005930", "OBSERVE_EVENT",
                52.0, 48.0, 35.0, 50.5, "caution_or_avoid",
                '{"long_score": 22.5, "caution_score": 71.5, "score_confidence": "medium"}',
                "test",
            ))
            conn.execute("""
                INSERT INTO gpt_analysis_scores (
                    gpt_call_id, analyzed_at, code, parse_status, decision,
                    risk_score, gpt_context_score, breakout_score, trend_score,
                    confidence, risk_flags_json, invalid_condition, summary,
                    entry_plan, raw_json, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                1, "2026-06-22 09:01:05.000000", "005930", "ok", "watch",
                42.0, 61.0, 30.0, 55.0, 70.0, "[]", None,
                "structured score", "observe only", "{}", None,
            ))
            feedback_payload = {
                "overview": {
                    "signal_count": 1,
                    "evaluated_count": 1,
                    "win_rate_60m_pct": 100.0,
                    "avg_net_return_60m_pct": 0.09,
                    "profit_factor_60m": 999.0,
                }
            }
            feedback_guidance = {
                "label": "positive_expectancy",
                "summary": "test guidance",
            }
            conn.execute("""
                INSERT INTO quant_feedback_snapshots (
                    generated_at, scope, code, window_start, window_end,
                    min_sample, signal_count, evaluated_count,
                    payload_json, guidance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-06-22 10:01:00.000000", "code", "005930",
                "2026-06-22 00:00:00.000000", "2026-06-22 10:00:00.000000",
                1, 1, 1, json.dumps(feedback_payload), json.dumps(feedback_guidance),
            ))
            conn.commit()
        finally:
            conn.close()

        try:
            snapshot = build_dashboard_snapshot(db_path, symbols=["005930"])
            html = render_dashboard_html(snapshot)
            self.assertEqual("005930", snapshot["rows"][0]["code"])
            self.assertEqual("OBSERVE_EVENT", snapshot["rows"][0]["action"])
            self.assertEqual("2026-06-22 10:01:00.000000", snapshot["latest"]["quant_feedback_snapshots"])
            self.assertEqual(1, len(snapshot["recent_score_compare"]))
            self.assertEqual("watch", snapshot["recent_score_compare"][0]["gpt_decision"])
            self.assertEqual(22.5, snapshot["recent_score_compare"][0]["long_score"])
            self.assertEqual(71.5, snapshot["recent_score_compare"][0]["caution_score"])
            self.assertEqual("medium", snapshot["recent_score_compare"][0]["score_confidence"])
            self.assertEqual(4, len(snapshot["horizon_summary"]))
            self.assertEqual(5, snapshot["horizon_summary"][0]["horizon_min"])
            self.assertEqual(1, snapshot["horizon_summary"][0]["evaluated_count"])
            self.assertGreaterEqual(len(snapshot["target_exit_scenarios"]), 1)
            self.assertEqual("positive_expectancy", snapshot["recent_quant_feedback"][0]["quality_label"])
            flow_symbols = {row["symbol"] for row in snapshot["investor_flows"]}
            self.assertIn("KOSPI", flow_symbols)
            self.assertIn("KOSDAQ", flow_symbols)
            self.assertIn("005930", flow_symbols)
            self.assertIn("Kiwoom Focused Dashboard", html)
            self.assertIn("005930", html)
            self.assertIn("Investor Flow", html)
            self.assertIn("KOSDAQ", html)
            self.assertIn("Horizon Summary", html)
            self.assertIn("Target Exit Scenarios", html)
            self.assertIn("Quant / GPT / Paper", html)
            self.assertIn("positive_expectancy", html)
        finally:
            os.unlink(db_path)

    def test_readable_summary_renders_sections_instead_of_raw_json(self):
        row = {
            "code": "005930",
            "name": "Samsung",
            "action": "OBSERVE_EVENT",
            "score": 55,
            "risk": "medium",
            "price": 70000,
            "tick_time": "2026-06-17 09:00:01.000000",
            "analysis_time": "2026-06-17 09:01:00.000000",
            "paper": {
                "evaluated_count": 3,
                "win_rate": 66.67,
                "avg_return_60m_pct": 0.42,
                "avg_max_loss_60m_pct": -0.21,
            },
            "summary_json": json.dumps({
                "code": "005930",
                "name": "Samsung",
                "market_snapshot": {
                    "change_rate": 0.5,
                    "day_open": 69800,
                    "day_high": 70100,
                    "day_low": 69700,
                    "strength": 105.0,
                },
                "events": [
                    {"type": "NEAR_VWAP_SUPPORT", "timeframe": "1m", "value": 0.123},
                ],
                "validation_signal": {
                    "action_hint": "OBSERVE_EVENT",
                    "confidence_score": 55,
                    "risk_level": "medium",
                    "stop_loss": 69000,
                    "target_1": 71000,
                    "target_2": 72000,
                    "reasons": ["Near VWAP support."],
                },
                "timeframes": {
                    "1m": {
                        "latest": {"close": 70000, "return_1bar_pct": 0.12},
                        "momentum": {"rsi14": 55.5},
                        "volume": {"volume_ratio_20": 1.1},
                        "vwap": {"vwap_distance_pct": 0.07},
                        "trend": {"consecutive_up_bars": 2, "consecutive_down_bars": 0},
                    }
                },
            }, ensure_ascii=False),
        }

        text = _readable_summary_text(row)

        self.assertIn("Decision: OBSERVE_EVENT", text)
        self.assertIn("Events", text)
        self.assertIn("Observation Anchors", text)
        self.assertIn("Timeframes", text)
        self.assertIn("Paper Feedback", text)
        self.assertNotIn('"timeframes"', text)


if __name__ == "__main__":
    unittest.main()
