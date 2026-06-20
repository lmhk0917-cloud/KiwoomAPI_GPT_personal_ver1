import json
import os
import tempfile
import unittest

from kiwoom_focused_dashboard import (
    _readable_summary_text,
    build_dashboard_snapshot,
    load_symbols,
    render_dashboard_html,
    save_symbols,
)
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
            conn.commit()
        finally:
            conn.close()

        try:
            snapshot = build_dashboard_snapshot(db_path, symbols=["005930"])
            html = render_dashboard_html(snapshot)
            self.assertEqual("005930", snapshot["rows"][0]["code"])
            self.assertEqual("OBSERVE_EVENT", snapshot["rows"][0]["action"])
            self.assertIn("Kiwoom Focused Dashboard", html)
            self.assertIn("005930", html)
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
