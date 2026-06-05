"""In-memory and SQLite persistence for ticks, analyses, events, and alerts.

The realtime app needs two storage modes at the same time:
- fast in-memory access for rolling indicator calculations
- durable SQLite records for later review, debugging, and paper-trade checks
"""

import json
import os
import sqlite3
from collections import deque
from datetime import datetime, timedelta

from app_paths import DEFAULT_DB_PATH, ensure_app_dirs
from config import MAX_TICKS_PER_CODE_MEMORY
from storage.schema import create_or_migrate_schema


class TickStore:
    """Store tick data in memory and optionally mirror it to SQLite."""

    def __init__(self, db_path=None, enable_sqlite=True):
        self.memory = {}
        self.enable_sqlite = enable_sqlite
        ensure_app_dirs()
        self.db_path = db_path or DEFAULT_DB_PATH
        self.conn = None

        if self.enable_sqlite:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self._create_tables()

    def _create_tables(self):
        create_or_migrate_schema(self.conn)

    def add_tick(self, tick):
        code = tick["code"]
        self._add_tick_to_memory(tick)
        self.save_tick(tick)

    def _add_tick_to_memory(self, tick):
        """Append one tick to the rolling in-memory buffer without DB writes."""
        code = tick["code"]

        if code not in self.memory:
            self.memory[code] = deque(maxlen=MAX_TICKS_PER_CODE_MEMORY)

        # The deque cap prevents long market sessions from exhausting memory.
        self.memory[code].append(tick)

    def preload_recent_ticks_from_db(self, codes, limit_per_code=5000, max_age_minutes=30):
        """Load recent persisted ticks into memory after app restart."""
        if not self.conn:
            return {}

        cutoff = (
            datetime.now() - timedelta(minutes=max_age_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S.%f")
        loaded_counts = {}

        for code in codes:
            rows = self.conn.execute("""
                SELECT
                    code, trade_time, price, change_rate, acc_volume,
                    tick_volume, open_price, high_price, low_price,
                    strength, received_at
                FROM ticks
                WHERE code = ?
                  AND received_at >= ?
                ORDER BY id DESC
                LIMIT ?
            """, (code, cutoff, limit_per_code)).fetchall()

            count = 0
            for row in reversed(rows):
                tick = {key: row[key] for key in row.keys()}
                self._add_tick_to_memory(tick)
                count += 1

            loaded_counts[code] = count

        return loaded_counts

    def save_tick(self, tick):
        """Persist one realtime tick."""
        if not self.conn:
            return

        self.conn.execute("""
            INSERT INTO ticks (
                code, trade_time, price, change_rate, acc_volume, tick_volume,
                open_price, high_price, low_price, strength, received_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tick.get("code"),
            tick.get("trade_time"),
            tick.get("price"),
            tick.get("change_rate"),
            tick.get("acc_volume"),
            tick.get("tick_volume"),
            tick.get("open_price"),
            tick.get("high_price"),
            tick.get("low_price"),
            tick.get("strength"),
            tick.get("received_at"),
        ))
        self.conn.commit()

    def save_analysis_result(self, summary, gpt_result, analyzed_at=None):
        """Persist one GPT result with both extracted columns and raw JSON."""
        if not self.conn:
            return

        analyzed_at = analyzed_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        analysis_summary = self._get_representative_summary(summary)
        latest = analysis_summary.get("latest", {})
        moving_average = analysis_summary.get("moving_average", {})
        momentum = analysis_summary.get("momentum", {})
        volume = analysis_summary.get("volume", {})
        vwap = analysis_summary.get("vwap", {})
        box_range = analysis_summary.get("box_range") or {}
        market_snapshot = summary.get("market_snapshot") or {}
        market_context = summary.get("market_context") or {}

        self.conn.execute("""
            INSERT INTO analysis_results (
                analyzed_at, code, name, current_price, rsi14,
                ma5, ma20, ma60, volume_ratio_5, volume_ratio_20,
                vwap, vwap_distance_pct, box_high, box_low, box_position,
                day_open, day_high, day_low, strength,
                market_context_json, summary_json, gpt_result
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            analyzed_at,
            summary.get("code"),
            summary.get("name"),
            latest.get("close"),
            momentum.get("rsi14"),
            moving_average.get("ma5"),
            moving_average.get("ma20"),
            moving_average.get("ma60"),
            volume.get("volume_ratio_5"),
            volume.get("volume_ratio_20"),
            vwap.get("vwap"),
            vwap.get("vwap_distance_pct"),
            box_range.get("box_high"),
            box_range.get("box_low"),
            box_range.get("current_position_in_box"),
            market_snapshot.get("day_open"),
            market_snapshot.get("day_high"),
            market_snapshot.get("day_low"),
            market_snapshot.get("strength"),
            json.dumps(market_context, ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False),
            gpt_result,
        ))
        self.conn.commit()

    def save_event_logs(self, summary, events, detected_at=None, gpt_requested=False, skip_reason=None):
        """Persist all events detected for one symbol in one analysis cycle."""
        if not self.conn or not events:
            return

        detected_at = detected_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        summary_json = json.dumps(summary, ensure_ascii=False)

        rows = []
        for event in events:
            rows.append((
                detected_at,
                summary.get("code"),
                summary.get("name"),
                self._sqlite_scalar(event.get("type")),
                self._sqlite_scalar(event.get("timeframe")),
                self._sqlite_scalar(event.get("message")),
                self._sqlite_scalar(event.get("value")),
                1 if gpt_requested else 0,
                self._sqlite_scalar(skip_reason),
                summary_json,
            ))

        self.conn.executemany("""
            INSERT INTO event_logs (
                detected_at, code, name, event_type, timeframe, message,
                value, gpt_requested, skip_reason, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self.conn.commit()

    def _sqlite_scalar(self, value):
        """Convert event payload fragments into sqlite-bindable values."""
        if value is None:
            return None

        if isinstance(value, (str, int, float)):
            return value

        if isinstance(value, bool):
            return int(value)

        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)

    def save_gpt_call_log(
        self,
        started_at,
        finished_at,
        status,
        requested_count,
        codes,
        model=None,
        duration_ms=None,
        prompt_chars=None,
        payload_original_chars=None,
        payload_compressed_chars=None,
        payload_compression_ratio=None,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        error_message=None,
        result_preview=None
    ):
        """Persist one GPT API call attempt."""
        if not self.conn:
            return

        self.conn.execute("""
            INSERT INTO gpt_call_logs (
                started_at, finished_at, status, requested_count,
                codes, model, duration_ms, prompt_chars, payload_original_chars,
                payload_compressed_chars, payload_compression_ratio, prompt_tokens,
                completion_tokens, total_tokens, error_message, result_preview
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            started_at,
            finished_at,
            status,
            requested_count,
            json.dumps(codes, ensure_ascii=False),
            model,
            duration_ms,
            prompt_chars,
            payload_original_chars,
            payload_compressed_chars,
            payload_compression_ratio,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            error_message,
            result_preview,
        ))
        self.conn.commit()

    def save_signal_log(self, signal, summary, detected_at=None):
        """Persist a pre-GPT validation signal and return its row id."""
        if not self.conn or not signal:
            return None

        detected_at = detected_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        cursor = self.conn.execute("""
            INSERT INTO signal_logs (
                detected_at, code, name, action_hint, confidence_score,
                risk_level, current_price, stop_loss, target_1, target_2,
                reason_json, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            detected_at,
            summary.get("code"),
            summary.get("name"),
            signal.get("action_hint"),
            signal.get("confidence_score"),
            signal.get("risk_level"),
            signal.get("current_price"),
            signal.get("stop_loss"),
            signal.get("target_1"),
            signal.get("target_2"),
            json.dumps(signal.get("reasons", []), ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False),
        ))
        self.conn.commit()
        return cursor.lastrowid

    def save_paper_trade_result(self, result):
        """Persist paper-trade evaluation metrics for a saved signal."""
        if not self.conn or not result:
            return

        self.conn.execute("""
            INSERT INTO paper_trade_results (
                signal_id, evaluated_at, code, entry_time, entry_price,
                return_5m_pct, return_10m_pct, return_30m_pct,
                return_60m_pct, max_gain_30m_pct, max_loss_30m_pct,
                max_gain_60m_pct, max_loss_60m_pct, target_1_hit,
                target_2_hit, stop_loss_hit, outcome_label, result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.get("signal_id"),
            result.get("evaluated_at"),
            result.get("code"),
            result.get("entry_time"),
            result.get("entry_price"),
            result.get("return_5m_pct"),
            result.get("return_10m_pct"),
            result.get("return_30m_pct"),
            result.get("return_60m_pct"),
            result.get("max_gain_30m_pct"),
            result.get("max_loss_30m_pct"),
            result.get("max_gain_60m_pct"),
            result.get("max_loss_60m_pct"),
            self._bool_to_int(result.get("target_1_hit")),
            self._bool_to_int(result.get("target_2_hit")),
            self._bool_to_int(result.get("stop_loss_hit")),
            result.get("outcome_label"),
            json.dumps(result, ensure_ascii=False),
        ))
        self.conn.commit()

    @staticmethod
    def _bool_to_int(value):
        if value is None:
            return None
        return 1 if bool(value) else 0

    def save_notification_logs(self, summary, events, results, message=None, sent_at=None):
        """Persist notification delivery results for audit/debugging."""
        if not self.conn or not results:
            return

        sent_at = sent_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        event_types = [event.get("type") for event in events or []]

        rows = []
        for result in results:
            rows.append((
                sent_at,
                summary.get("code"),
                summary.get("name"),
                result.get("channel"),
                result.get("status"),
                json.dumps(event_types, ensure_ascii=False),
                message,
                result.get("error_message"),
            ))

        self.conn.executemany("""
            INSERT INTO notification_logs (
                sent_at, code, name, channel, status, event_types,
                message, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self.conn.commit()

    def save_market_context_snapshot(
        self,
        scope,
        section,
        payload,
        code=None,
        collected_at=None,
        source=None,
        reliability=None,
        weight=None,
        summary=None
    ):
        """Persist one market-context snapshot without changing GPT payload size."""
        if not self.conn or not section or payload is None:
            return None

        collected_at = collected_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        scope = scope if scope in ("global", "code") else ("code" if code else "global")
        payload_data = payload if isinstance(payload, dict) else {"value": payload}

        source = source if source is not None else payload_data.get("source")
        asof = payload_data.get("asof")
        reliability = reliability if reliability is not None else payload_data.get("reliability")
        weight = weight if weight is not None else payload_data.get("weight")
        summary = summary if summary is not None else payload_data.get("summary")

        cursor = self.conn.execute("""
            INSERT INTO market_context_snapshots (
                collected_at, scope, code, section, source, asof,
                reliability, weight, summary, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            collected_at,
            scope,
            code,
            section,
            source,
            asof,
            reliability,
            weight,
            summary,
            json.dumps(payload_data, ensure_ascii=False),
        ))
        self.conn.commit()
        return cursor.lastrowid

    def get_recent_market_context_snapshots(self, code=None, section=None, limit=50):
        """Return recent market-context snapshots for reports or UI checks."""
        if not self.conn:
            return []

        where = []
        params = []

        if code:
            where.append("code = ?")
            params.append(code)

        if section:
            where.append("section = ?")
            params.append(section)

        where_sql = "WHERE " + " AND ".join(where) if where else ""
        params.append(limit)

        rows = self.conn.execute("""
            SELECT *
            FROM market_context_snapshots
            {}
            ORDER BY collected_at DESC
            LIMIT ?
        """.format(where_sql), params).fetchall()

        return [dict(row) for row in rows]

    def save_historical_bars(self, bars):
        """Upsert historical OHLCV bars fetched from Kiwoom TR."""
        if not self.conn or not bars:
            return 0

        rows = []
        for bar in bars:
            rows.append((
                bar.get("code"),
                bar.get("timeframe"),
                bar.get("bar_time"),
                bar.get("open"),
                bar.get("high"),
                bar.get("low"),
                bar.get("close"),
                bar.get("volume"),
                bar.get("trading_value"),
                bar.get("source"),
                bar.get("fetched_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            ))

        self.conn.executemany("""
            INSERT OR REPLACE INTO historical_bars (
                code, timeframe, bar_time, open, high, low, close,
                volume, trading_value, source, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self.conn.commit()
        return len(rows)

    def get_historical_price_context(self, code):
        """Summarize backfilled daily/minute bars for GPT context."""
        return {
            "daily": self._summarize_historical_bars(code, "day", limit=260),
            "minute_1m": self._summarize_historical_bars(code, "1m", limit=390),
            "minute_3m": self._summarize_historical_bars(code, "3m", limit=130),
            "minute_5m": self._summarize_historical_bars(code, "5m", limit=78),
        }

    def _summarize_historical_bars(self, code, timeframe, limit):
        if not self.conn:
            return {
                "timeframe": timeframe,
                "sample_size": 0,
                "note": "SQLite is disabled.",
            }

        rows = self.conn.execute("""
            SELECT bar_time, open, high, low, close, volume
            FROM historical_bars
            WHERE code = ?
              AND timeframe = ?
            ORDER BY bar_time DESC
            LIMIT ?
        """, (code, timeframe, limit)).fetchall()

        if not rows:
            return {
                "timeframe": timeframe,
                "sample_size": 0,
                "note": "No backfilled bars yet.",
            }

        chronological = list(reversed(rows))
        closes = [self._to_float(row["close"]) for row in chronological if self._to_float(row["close"]) is not None]
        highs = [self._to_float(row["high"]) for row in chronological if self._to_float(row["high"]) is not None]
        lows = [self._to_float(row["low"]) for row in chronological if self._to_float(row["low"]) is not None]
        volumes = [self._to_float(row["volume"]) for row in chronological if self._to_float(row["volume"]) is not None]

        latest = chronological[-1]
        latest_close = self._to_float(latest["close"])
        previous_close = self._to_float(chronological[-2]["close"]) if len(chronological) >= 2 else None
        ma5 = self._avg(closes[-5:]) if len(closes) >= 5 else None
        ma20 = self._avg(closes[-20:]) if len(closes) >= 20 else None

        return {
            "timeframe": timeframe,
            "sample_size": len(rows),
            "oldest_bar_time": chronological[0]["bar_time"],
            "latest_bar_time": latest["bar_time"],
            "latest_close": latest_close,
            "return_1bar_pct": self._pct_change(latest_close, previous_close),
            "return_5bar_pct": self._return_over_bars(closes, 5),
            "return_20bar_pct": self._return_over_bars(closes, 20),
            "ma5": ma5,
            "ma20": ma20,
            "price_above_ma5": latest_close > ma5 if latest_close is not None and ma5 is not None else None,
            "price_above_ma20": latest_close > ma20 if latest_close is not None and ma20 is not None else None,
            "ma5_distance_pct": self._distance_from_level(latest_close, ma5),
            "ma20_distance_pct": self._distance_from_level(latest_close, ma20),
            "high_20bar": self._max_tail(highs, 20),
            "low_20bar": self._min_tail(lows, 20),
            "high_60bar": self._max_tail(highs, 60),
            "low_60bar": self._min_tail(lows, 60),
            "distance_from_20bar_high_pct": self._distance_from_level(latest_close, self._max_tail(highs, 20)),
            "distance_from_20bar_low_pct": self._distance_from_level(latest_close, self._min_tail(lows, 20)),
            "avg_volume_5bar": self._avg(volumes[-5:]),
            "avg_volume_20bar": self._avg(volumes[-20:]),
            "volume_ratio_5bar": self._volume_ratio(volumes, 5),
            "volume_ratio_20bar": self._volume_ratio(volumes, 20),
            "note": None,
        }

    def get_signal_performance_context(self, code, limit=50):
        """Summarize recent paper-trade outcomes for GPT context."""
        empty_context = {
            "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "sample_size": 0,
            "evaluated_count": 0,
            "tradeable_long_actions": [
                "WATCH_REBOUND",
                "WATCH_PULLBACK",
                "WATCH_BREAKOUT",
                "WATCH_SUPPORT",
                "WATCH_MOMENTUM",
            ],
            "avg_return_5m_pct": None,
            "avg_return_10m_pct": None,
            "avg_return_30m_pct": None,
            "avg_return_60m_pct": None,
            "win_rate_30m_pct": None,
            "win_rate_60m_pct": None,
            "avg_max_gain_30m_pct": None,
            "avg_max_loss_30m_pct": None,
            "avg_max_gain_60m_pct": None,
            "avg_max_loss_60m_pct": None,
            "target_1_hit_rate_pct": None,
            "target_2_hit_rate_pct": None,
            "stop_loss_hit_rate_pct": None,
            "action_stats": [],
            "recent_signals": [],
            "learning_feedback": {
                "regime_note": None,
                "avoid_actions": [],
                "prefer_actions": [],
                "guidance": "No evaluated data yet. Do not infer strategy quality.",
            },
            "note": "No evaluated historical signals yet.",
        }

        if not self.conn:
            return empty_context

        rows = self.conn.execute("""
            SELECT
                s.id,
                s.detected_at,
                s.action_hint,
                s.confidence_score,
                s.risk_level,
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
            WHERE s.code = ?
            ORDER BY s.detected_at DESC
            LIMIT ?
        """, (code, limit)).fetchall()

        if not rows:
            return empty_context

        evaluated_rows = [
            row for row in rows
            if row["return_60m_pct"] is not None or row["return_30m_pct"] is not None
        ]
        return_5m_values = [row["return_5m_pct"] for row in evaluated_rows if row["return_5m_pct"] is not None]
        return_10m_values = [row["return_10m_pct"] for row in evaluated_rows if row["return_10m_pct"] is not None]
        return_30m_values = [row["return_30m_pct"] for row in evaluated_rows if row["return_30m_pct"] is not None]
        return_60m_values = [row["return_60m_pct"] for row in evaluated_rows if row["return_60m_pct"] is not None]
        max_gain_30m_values = [row["max_gain_30m_pct"] for row in evaluated_rows if row["max_gain_30m_pct"] is not None]
        max_loss_30m_values = [row["max_loss_30m_pct"] for row in evaluated_rows if row["max_loss_30m_pct"] is not None]
        max_gain_60m_values = [row["max_gain_60m_pct"] for row in evaluated_rows if row["max_gain_60m_pct"] is not None]
        max_loss_60m_values = [row["max_loss_60m_pct"] for row in evaluated_rows if row["max_loss_60m_pct"] is not None]

        action_groups = {}
        for row in rows:
            action_hint = row["action_hint"] or "UNKNOWN"
            action_groups.setdefault(action_hint, []).append(row)

        action_stats = []
        for action_hint, action_rows in action_groups.items():
            action_evaluated_rows = [
                row for row in action_rows
                if row["return_60m_pct"] is not None or row["return_30m_pct"] is not None
            ]
            action_return_30m = [
                row["return_30m_pct"]
                for row in action_evaluated_rows
                if row["return_30m_pct"] is not None
            ]
            action_return_60m = [
                row["return_60m_pct"]
                for row in action_evaluated_rows
                if row["return_60m_pct"] is not None
            ]
            action_stats.append({
                "action_hint": action_hint,
                "sample_size": len(action_rows),
                "evaluated_count": len(action_evaluated_rows),
                "avg_return_30m_pct": self._avg(action_return_30m),
                "avg_return_60m_pct": self._avg(action_return_60m),
                "win_rate_30m_pct": self._win_rate(action_return_30m),
                "win_rate_60m_pct": self._win_rate(action_return_60m),
                "target_1_hit_rate_pct": self._hit_rate(action_evaluated_rows, "target_1_hit"),
                "target_2_hit_rate_pct": self._hit_rate(action_evaluated_rows, "target_2_hit"),
                "stop_loss_hit_rate_pct": self._hit_rate(action_evaluated_rows, "stop_loss_hit"),
                "outcome_counts": self._value_counts(action_evaluated_rows, "outcome_label"),
            })

        action_stats.sort(
            key=lambda item: (
                item["evaluated_count"],
                item["avg_return_60m_pct"] if item["avg_return_60m_pct"] is not None else -999
            ),
            reverse=True
        )

        recent_signals = []
        for row in rows[:5]:
            recent_signals.append({
                "detected_at": row["detected_at"],
                "action_hint": row["action_hint"],
                "confidence_score": row["confidence_score"],
                "risk_level": row["risk_level"],
                "return_30m_pct": row["return_30m_pct"],
                "return_60m_pct": row["return_60m_pct"],
                "target_1_hit": row["target_1_hit"],
                "target_2_hit": row["target_2_hit"],
                "stop_loss_hit": row["stop_loss_hit"],
                "outcome_label": row["outcome_label"],
            })

        learning_feedback = self._build_learning_feedback(
            action_stats=action_stats,
            evaluated_count=len(evaluated_rows),
            avg_return_60m_pct=self._avg(return_60m_values),
            win_rate_60m_pct=self._win_rate(return_60m_values),
            stop_loss_hit_rate_pct=self._hit_rate(evaluated_rows, "stop_loss_hit"),
        )

        return {
            "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "sample_size": len(rows),
            "evaluated_count": len(evaluated_rows),
            "tradeable_long_actions": empty_context["tradeable_long_actions"],
            "avg_return_5m_pct": self._avg(return_5m_values),
            "avg_return_10m_pct": self._avg(return_10m_values),
            "avg_return_30m_pct": self._avg(return_30m_values),
            "avg_return_60m_pct": self._avg(return_60m_values),
            "win_rate_30m_pct": self._win_rate(return_30m_values),
            "win_rate_60m_pct": self._win_rate(return_60m_values),
            "avg_max_gain_30m_pct": self._avg(max_gain_30m_values),
            "avg_max_loss_30m_pct": self._avg(max_loss_30m_values),
            "avg_max_gain_60m_pct": self._avg(max_gain_60m_values),
            "avg_max_loss_60m_pct": self._avg(max_loss_60m_values),
            "target_1_hit_rate_pct": self._hit_rate(evaluated_rows, "target_1_hit"),
            "target_2_hit_rate_pct": self._hit_rate(evaluated_rows, "target_2_hit"),
            "stop_loss_hit_rate_pct": self._hit_rate(evaluated_rows, "stop_loss_hit"),
            "action_stats": action_stats[:10],
            "recent_signals": recent_signals,
            "learning_feedback": learning_feedback,
            "note": None if evaluated_rows else "Signals exist, but no completed paper-trade evaluations yet.",
        }

    def _build_learning_feedback(
        self,
        action_stats,
        evaluated_count,
        avg_return_60m_pct,
        win_rate_60m_pct,
        stop_loss_hit_rate_pct,
    ):
        """Convert paper-trade stats into compact GPT guidance."""
        feedback = {
            "regime_note": None,
            "avoid_actions": [],
            "prefer_actions": [],
            "guidance": None,
        }

        if evaluated_count < 5:
            feedback["guidance"] = "Sample is too small. Use this only as weak evidence."
            return feedback

        if (
            avg_return_60m_pct is not None
            and avg_return_60m_pct < 0
            and win_rate_60m_pct is not None
            and win_rate_60m_pct < 40
        ):
            feedback["regime_note"] = (
                "Recent long validation signals are underperforming. "
                "Require stronger trend reversal or breakout confirmation."
            )

        if stop_loss_hit_rate_pct is not None and stop_loss_hit_rate_pct >= 50:
            feedback["guidance"] = (
                "Stop-loss hit rate is high. Penalize early rebound/support entries "
                "unless 3m/5m trend and VWAP recovery confirm."
            )
        else:
            feedback["guidance"] = (
                "Use action-level stats to adjust confidence; do not override live price action."
            )

        for item in action_stats:
            action_hint = item.get("action_hint")
            evaluated = item.get("evaluated_count") or 0
            avg60 = item.get("avg_return_60m_pct")
            win60 = item.get("win_rate_60m_pct")
            stop_rate = item.get("stop_loss_hit_rate_pct")

            if evaluated < 5:
                continue

            if (
                (avg60 is not None and avg60 < 0)
                or (win60 is not None and win60 < 40)
                or (stop_rate is not None and stop_rate >= 50)
            ):
                feedback["avoid_actions"].append({
                    "action_hint": action_hint,
                    "evaluated_count": evaluated,
                    "avg_return_60m_pct": avg60,
                    "win_rate_60m_pct": win60,
                    "stop_loss_hit_rate_pct": stop_rate,
                    "adjustment": "lower_confidence_or_wait_for_confirmation",
                })
            elif avg60 is not None and avg60 > 0 and win60 is not None and win60 >= 50:
                feedback["prefer_actions"].append({
                    "action_hint": action_hint,
                    "evaluated_count": evaluated,
                    "avg_return_60m_pct": avg60,
                    "win_rate_60m_pct": win60,
                    "adjustment": "eligible_for_higher_confidence_when_live_setup_matches",
                })

        feedback["avoid_actions"] = feedback["avoid_actions"][:5]
        feedback["prefer_actions"] = feedback["prefer_actions"][:3]
        return feedback

    def _avg(self, values):
        """Return a rounded average for a list of numeric values."""
        if not values:
            return None

        return round(sum(float(value) for value in values) / len(values), 3)

    def _win_rate(self, values):
        """Return percentage of positive returns."""
        if not values:
            return None

        wins = len([value for value in values if value > 0])
        return round(wins / len(values) * 100, 2)

    def _hit_rate(self, rows, column):
        """Return percentage of evaluated rows where a level flag is true."""
        values = [row[column] for row in rows if row[column] is not None]
        if not values:
            return None

        hits = len([value for value in values if int(value) == 1])
        return round(hits / len(values) * 100, 2)

    def _value_counts(self, rows, column):
        """Return small frequency summary for categorical evaluation results."""
        counts = {}
        for row in rows:
            value = row[column]
            if value is None:
                continue
            counts[value] = counts.get(value, 0) + 1

        return counts

    def _to_float(self, value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _pct_change(self, current, previous):
        if current is None or previous in (None, 0):
            return None
        return round((current - previous) / previous * 100, 3)

    def _return_over_bars(self, closes, bars):
        if len(closes) <= bars:
            return None
        return self._pct_change(closes[-1], closes[-1 - bars])

    def _max_tail(self, values, count):
        tail = values[-count:]
        return round(max(tail), 3) if tail else None

    def _min_tail(self, values, count):
        tail = values[-count:]
        return round(min(tail), 3) if tail else None

    def _distance_from_level(self, price, level):
        if price is None or level in (None, 0):
            return None
        return round((price - level) / level * 100, 3)

    def _volume_ratio(self, volumes, count):
        if len(volumes) < count + 1:
            return None
        baseline = self._avg(volumes[-count - 1:-1])
        if baseline in (None, 0):
            return None
        return round(volumes[-1] / baseline, 3)

    def _get_representative_summary(self, summary):
        """Use the 1-minute timeframe as the compact DB column source."""
        timeframes = summary.get("timeframes")

        if not timeframes:
            return summary

        if timeframes.get("1m"):
            return timeframes["1m"]

        for timeframe_summary in timeframes.values():
            return timeframe_summary

        return {}

    def get_recent_ticks(self, code):
        if code not in self.memory:
            return []

        return list(self.memory[code])

    def count(self, code):
        if code not in self.memory:
            return 0

        return len(self.memory[code])

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
