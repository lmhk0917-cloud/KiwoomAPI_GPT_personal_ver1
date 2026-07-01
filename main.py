"""Realtime Kiwoom analysis application entrypoint.

The event loop is owned by PyQt because Kiwoom OpenAPI+ exposes COM events
through QAxWidget. This module wires together realtime ticks, indicator
summaries, event filtering, GPT analysis, database persistence, and alerts.
"""

import os
import sys
import traceback
from datetime import datetime

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from app_paths import setup_runtime_logging
from config import (
    ENABLE_MACRO_CONTEXT_CRAWL,
    ENABLE_INTRADAY_NEWS_CONTEXT,
    ENABLE_PAPER_TRADE_EVALUATION,
    ENABLE_POST_MARKET_FEEDBACK,
    GPT_ANALYSIS_INTERVAL_SEC,
    GPT_MAX_SYMBOLS_PER_CALL,
    GPT_MIN_SIGNAL_SCORE,
    GPT_FORCE_EVENT_TYPES,
    MACRO_CONTEXT_REFRESH_INTERVAL_SEC,
    GPT_STRONG_EVENT_TYPES,
    MARKET_BENCHMARK_CODES,
    MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH,
    MARKET_CONTEXT_TR_REQUEST_DELAY_MS,
    MARKET_REGULAR_CLOSE_TIME,
    PAPER_TRADE_EVALUATION_LIMIT,
    POST_MARKET_FEEDBACK_LOOKBACK_DAYS,
    POST_MARKET_FEEDBACK_MIN_SAMPLE,
    POST_MARKET_FEEDBACK_TIME,
    POST_MARKET_STOP_ANALYSIS_AFTER_FINALIZE,
    PRELOAD_TICKS_MAX_AGE_MINUTES,
    PRELOAD_TICKS_PER_CODE,
    NEWS_CONTEXT_COOLDOWN_SEC,
    NEWS_CONTEXT_TRIGGER_EVENT_TYPES,
    TELEGRAM_ALLOWED_ACTION_HINTS,
    TELEGRAM_ALWAYS_NOTIFY_EVENT_TYPES,
    TELEGRAM_MIN_SIGNAL_SCORE,
    TELEGRAM_NOTIFY_ONLY_HIGH_PRIORITY,
    WATCH_CODES,
)
from data_store import TickStore
from event_detector import detect_gpt_events
from gpt_analyzer import GPTAnalyzer
from gpt_result_parser import parse_gpt_analysis_scores
from indicators import make_market_snapshot, summarize_multi_timeframes_for_gpt
from kiwoom_client import KiwoomClient
from macro_context_fetcher import fetch_macro_context, fetch_news_context
from market_context import MarketContextStore
from notifier import Notifier
from paper_trade_simulator import evaluate_signal as evaluate_paper_signal
from paper_trade_simulator import fetch_pending_signals
from quant_signal_score import build_quant_signal_score
from settings_store import SettingsStore
from shared_context_auto_export import export_shared_context
from signal_generator import generate_validation_signal
from env_loader import load_project_env


load_project_env()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class RealtimeStrategyApp:
    def __init__(self, require_existing_login=False):
        self.log_path = setup_runtime_logging("main")
        self.tick_store = TickStore()
        self.settings_store = SettingsStore(conn=self.tick_store.conn)
        self.settings = self.settings_store.get_runtime_settings()
        self.current_timer_interval_sec = self._get_setting(
            "GPT_ANALYSIS_INTERVAL_SEC",
            GPT_ANALYSIS_INTERVAL_SEC
        )
        self.watch_codes = self._normalize_watch_codes(self._get_setting("WATCH_CODES", WATCH_CODES))
        self.market_benchmark_codes = self._normalize_watch_codes(
            self._get_setting("MARKET_BENCHMARK_CODES", MARKET_BENCHMARK_CODES)
        )
        self.last_gpt_called_at = {}
        self.last_notified_at = {}
        self.last_context_tr_requested_at = None
        self.pending_context_tr_requests = []
        self.context_tr_request_delay_ms = MARKET_CONTEXT_TR_REQUEST_DELAY_MS
        self.last_macro_context_crawled_at = None
        self.last_news_context_checked_at = {}
        self.last_market_status_snapshot_key = None
        self.last_shared_context_export_at = None
        self.post_market_feedback_done_date = None
        self.notifier = Notifier()
        self.market_context_store = MarketContextStore()
        self._preload_recent_ticks()

        self.kiwoom = KiwoomClient(
            tick_store=self.tick_store,
            codes=self._get_realtime_codes(),
            market_context_store=self.market_context_store,
            require_existing_login=require_existing_login
        )

        self.gpt = GPTAnalyzer(api_key=OPENAI_API_KEY)

        self.timer = QTimer()
        self.timer.timeout.connect(self.run_analysis_safely)
        self.timer.start(self.current_timer_interval_sec * 1000)

        # Kiwoom login is asynchronous. Schedule it after the Qt event loop
        # starts so timed tests can still install their shutdown timer first.
        QTimer.singleShot(0, self.kiwoom.login)

    def run_analysis_safely(self):
        """Keep the Qt event loop alive if one analysis cycle raises."""
        try:
            self.run_analysis()
        except Exception:
            print("ANALYSIS_CYCLE_EXCEPTION")
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()

    def run_analysis(self):
        print("\n========== Analysis cycle ==========")

        self._reload_runtime_settings()
        now = datetime.now()
        detected_at = now.strftime("%Y-%m-%d %H:%M:%S.%f")
        market_summaries = []
        self.market_context_store.reload()
        self._maybe_save_market_status_snapshot(now)

        if self._handle_post_market_feedback(now):
            return

        if not self.kiwoom.is_logged_in:
            print("Kiwoom login not ready. Skip analysis/TR requests this cycle.")
            return

        self._maybe_refresh_macro_context(now)
        self._maybe_request_market_context_trs(now)
        self._update_benchmark_etf_context()

        for code, name in self.watch_codes.items():
            tick_count = self.tick_store.count(code)

            if tick_count < self._get_setting("MIN_TICKS_FOR_ANALYSIS", 30):
                print(f"{name}({code}) not enough ticks: {tick_count}")
                continue

            ticks = self.tick_store.get_recent_ticks(code)

            summary = summarize_multi_timeframes_for_gpt(
                code=code,
                name=name,
                ticks=ticks,
                drop_last=True
            )

            if not summary:
                continue

            # File-based context and realtime context are merged here before event detection.
            summary["detected_at"] = detected_at
            summary["market_context"] = self.market_context_store.get_context(code)
            summary["historical_price_context"] = self.tick_store.get_historical_price_context(code)
            summary["historical_signal_stats"] = self.tick_store.get_signal_performance_context(code)

            events = detect_gpt_events(summary, settings=self.settings)
            summary["events"] = events

            if self._get_setting("ENABLE_EVENT_FILTER", True) and not events:
                print(f"{name}({code}) GPT event none")
                continue

            if self._get_setting("ENABLE_EVENT_FILTER", True) and not self._can_call_gpt(code, now):
                self.tick_store.save_event_logs(
                    summary=summary,
                    events=events,
                    detected_at=detected_at,
                    gpt_requested=False,
                    skip_reason="cooldown"
                )
                print(f"{name}({code}) GPT cooldown active")
                continue

            if events:
                signal = generate_validation_signal(summary, settings=self.settings)

                if signal:
                    summary["validation_signal"] = signal
                    signal_id = self.tick_store.save_signal_log(
                        signal=signal,
                        summary=summary,
                        detected_at=detected_at
                    )
                    quant_score = build_quant_signal_score(
                        signal=signal,
                        summary=summary,
                        signal_id=signal_id,
                        scored_at=detected_at,
                    )
                    self.tick_store.save_quant_signal_score(quant_score)
                    print(
                        f"{name}({code}) signal #{signal_id}: "
                        f"{signal['action_hint']} score={signal['confidence_score']}"
                    )

                self._notify_event(
                    summary=summary,
                    events=events,
                    signal=signal,
                    now=now
                )

                gpt_eligible, skip_reason = self._is_gpt_eligible(summary, events, signal)
                print(f"{name}({code}) GPT event:", [event["type"] for event in events])

                if gpt_eligible:
                    self._maybe_refresh_news_context(
                        summary=summary,
                        events=events,
                        signal=signal,
                        now=now
                    )
                    summary["market_context"] = self.market_context_store.get_context(code)

                self.tick_store.save_event_logs(
                    summary=summary,
                    events=events,
                    detected_at=detected_at,
                    gpt_requested=gpt_eligible,
                    skip_reason=None if gpt_eligible else skip_reason
                )

                if gpt_eligible:
                    market_summaries.append(summary)
                else:
                    print(f"{name}({code}) GPT skipped:", skip_reason)

        self._evaluate_pending_paper_trades()

        if not market_summaries:
            print("No GPT trigger events yet.")
            self._maybe_export_shared_context(reason="intraday_cycle_no_gpt")
            return

        print("GPT eligible symbols before rank:", len(market_summaries))
        sys.stdout.flush()

        market_summaries = self._rank_gpt_summaries(market_summaries)

        print("GPT request symbols:", len(market_summaries))
        sys.stdout.flush()

        started_at = datetime.now()
        result = self.gpt.analyze(market_summaries, settings=self.settings)
        finished_at = datetime.now()
        payload_stats = self.gpt.last_payload_stats or {}

        status = "failed" if self.gpt.last_error_message else "success"
        gpt_call_id = self.tick_store.save_gpt_call_log(
            started_at=started_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            finished_at=finished_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            status=status,
            requested_count=len(market_summaries),
            codes=[summary["code"] for summary in market_summaries],
            model=self.gpt.last_model,
            duration_ms=int((finished_at - started_at).total_seconds() * 1000),
            prompt_chars=self.gpt.last_prompt_chars,
            payload_original_chars=payload_stats.get("original_json_chars"),
            payload_compressed_chars=payload_stats.get("compressed_json_chars"),
            payload_compression_ratio=payload_stats.get("compression_ratio"),
            prompt_tokens=self.gpt.last_usage.get("prompt_tokens"),
            completion_tokens=self.gpt.last_usage.get("completion_tokens"),
            total_tokens=self.gpt.last_usage.get("total_tokens"),
            error_message=self.gpt.last_error_message,
            result_preview=result[:500] if result else None
        )
        score_rows = parse_gpt_analysis_scores(
            result_text=result,
            summaries=market_summaries,
            gpt_call_id=gpt_call_id,
            analyzed_at=finished_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        )
        saved_scores = self.tick_store.save_gpt_analysis_scores(score_rows)
        print("Structured GPT score rows saved:", saved_scores)

        for summary in market_summaries:
            self.last_gpt_called_at[summary["code"]] = now
            self.tick_store.save_analysis_result(
                summary=summary,
                gpt_result=result,
                analyzed_at=finished_at.strftime("%Y-%m-%d %H:%M:%S.%f")
            )

        self._maybe_export_shared_context(reason="intraday_gpt_analysis_saved")

        print("\n========== GPT analysis result ==========")
        print(result)
        print("=========================================\n")

    def _handle_post_market_feedback(self, now):
        """Run post-market paper/quant feedback once and block stale analysis."""
        if not self._is_post_market_feedback_time(now):
            return False

        date_key = now.strftime("%Y-%m-%d")
        if self.post_market_feedback_done_date == date_key:
            return True

        if not self._get_setting("ENABLE_POST_MARKET_FEEDBACK", ENABLE_POST_MARKET_FEEDBACK):
            print("POST_MARKET_ANALYSIS_SKIPPED=feedback_disabled")
            self.post_market_feedback_done_date = date_key
            return True

        print("POST_MARKET_FEEDBACK_STARTED={}".format(date_key))
        since = "{} 00:00:00".format(date_key)
        evaluated = self._evaluate_pending_paper_trades(
            allow_partial=True,
            since=since,
            refresh_feedback=False,
        )
        snapshots = self._save_quant_feedback_snapshot()
        print("POST_MARKET_PAPER_EVALUATED={}".format(evaluated))
        print("POST_MARKET_QUANT_SNAPSHOTS={}".format(snapshots))
        self._maybe_export_shared_context(reason="post_market_feedback", force=True)
        self.post_market_feedback_done_date = date_key

        if self._get_setting(
            "POST_MARKET_STOP_ANALYSIS_AFTER_FINALIZE",
            POST_MARKET_STOP_ANALYSIS_AFTER_FINALIZE
        ):
            try:
                self.timer.stop()
                print("POST_MARKET_ANALYSIS_TIMER_STOPPED=True")
            except Exception as exc:
                print("POST_MARKET_ANALYSIS_TIMER_STOP_ERROR={}".format(exc))

        return True

    def _maybe_export_shared_context(self, reason, force=False):
        if (
            reason == "intraday_cycle_no_gpt"
            and not force
            and os.environ.get("KIWOOM_SHARED_CONTEXT_EXPORT_ON_NO_GPT", "").lower() not in ("1", "true", "yes")
        ):
            print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_SKIPPED=no_gpt_cycle_disabled")
            return False

        now = datetime.now()
        cooldown_sec = int(os.environ.get("KIWOOM_SHARED_CONTEXT_EXPORT_COOLDOWN_SEC", "300"))
        if (
            not force
            and self.last_shared_context_export_at is not None
            and (now - self.last_shared_context_export_at).total_seconds() < cooldown_sec
        ):
            print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_SKIPPED=cooldown")
            return False
        ok = export_shared_context(reason=reason, blocking=force)
        if ok:
            self.last_shared_context_export_at = now
        return ok

    def _is_post_market_feedback_time(self, now):
        """Return True once local time has passed the configured feedback time."""
        time_text = self._get_setting("POST_MARKET_FEEDBACK_TIME", POST_MARKET_FEEDBACK_TIME)
        target = self._parse_hhmm_time(time_text, default=POST_MARKET_FEEDBACK_TIME)
        if target is None:
            return False
        return now.time() >= target

    def _parse_hhmm_time(self, value, default=None):
        text = str(value or default or "").strip()
        try:
            return datetime.strptime(text, "%H:%M").time()
        except ValueError:
            return None

    def _evaluate_pending_paper_trades(self, allow_partial=False, since=None, refresh_feedback=True):
        """Evaluate saved validation signals when enough future ticks exist."""
        if not self.tick_store.conn:
            return 0

        if not self._get_setting("ENABLE_PAPER_TRADE_EVALUATION", ENABLE_PAPER_TRADE_EVALUATION):
            return 0

        limit = self._get_setting("PAPER_TRADE_EVALUATION_LIMIT", PAPER_TRADE_EVALUATION_LIMIT)

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = PAPER_TRADE_EVALUATION_LIMIT

        if limit <= 0:
            return 0

        signals = fetch_pending_signals(self.tick_store, limit=limit, since=since)
        evaluated = 0

        for signal in signals:
            result = evaluate_paper_signal(self.tick_store, signal, allow_partial=allow_partial)
            if not result:
                continue

            self.tick_store.save_paper_trade_result(result)
            evaluated += 1

        if evaluated:
            print("Paper-trade evaluations saved:", evaluated)
            if refresh_feedback:
                self._save_quant_feedback_snapshot()
        return evaluated

    def _save_quant_feedback_snapshot(self):
        """Refresh quant-style feedback after new paper-trade rows are saved."""
        try:
            from quant_feedback import save_feedback_snapshots

            days = self._get_setting(
                "POST_MARKET_FEEDBACK_LOOKBACK_DAYS",
                POST_MARKET_FEEDBACK_LOOKBACK_DAYS
            )
            min_sample = self._get_setting(
                "POST_MARKET_FEEDBACK_MIN_SAMPLE",
                POST_MARKET_FEEDBACK_MIN_SAMPLE
            )
            try:
                days = int(days)
            except (TypeError, ValueError):
                days = POST_MARKET_FEEDBACK_LOOKBACK_DAYS
            try:
                min_sample = int(min_sample)
            except (TypeError, ValueError):
                min_sample = POST_MARKET_FEEDBACK_MIN_SAMPLE

            snapshots = save_feedback_snapshots(
                store=self.tick_store,
                days=days,
                min_sample=min_sample,
                codes=list(self.watch_codes.keys()),
            )
            print("Quant feedback snapshots saved:", len(snapshots))
            return len(snapshots)
        except Exception:
            print("QUANT_FEEDBACK_EXCEPTION")
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            return 0

    def _can_call_gpt(self, code, now):
        """Apply per-symbol cooldown to avoid repeated GPT calls on the same move."""
        last_called_at = self.last_gpt_called_at.get(code)

        if not last_called_at:
            return True

        elapsed_sec = (now - last_called_at).total_seconds()
        return elapsed_sec >= self._get_setting("GPT_COOLDOWN_SEC", 180)

    def _is_gpt_eligible(self, summary, events, signal):
        """Keep notifications broad while sending GPT only stronger candidates."""
        if not events:
            return False, "no_event"

        min_score = self._get_setting("GPT_MIN_SIGNAL_SCORE", GPT_MIN_SIGNAL_SCORE)
        try:
            min_score = float(min_score)
        except (TypeError, ValueError):
            min_score = GPT_MIN_SIGNAL_SCORE

        score = None
        if signal:
            try:
                score = float(signal.get("confidence_score"))
            except (TypeError, ValueError):
                score = None

        strong_event_types = set(self._get_setting("GPT_STRONG_EVENT_TYPES", GPT_STRONG_EVENT_TYPES) or [])
        force_event_types = set(self._get_setting("GPT_FORCE_EVENT_TYPES", GPT_FORCE_EVENT_TYPES) or [])
        event_types = [event.get("type") for event in events or []]
        critical_event_types = {
            "MARKET_SIDECAR_ACTIVE",
            "MARKET_CIRCUIT_BREAKER_ACTIVE",
            "MARKET_VI_ACTIVE",
        }

        if critical_event_types.intersection(event_types) or force_event_types.intersection(event_types):
            return True, None

        strong_event_count = sum(1 for event_type in event_types if event_type in strong_event_types)

        if score is not None and score >= min_score:
            return True, None
        if strong_event_count >= 2:
            return True, None

        return False, "weak_event_or_low_score"

    def _rank_gpt_summaries(self, summaries):
        """Limit each GPT call to the strongest symbols by score and event count."""
        max_symbols = self._get_setting("GPT_MAX_SYMBOLS_PER_CALL", GPT_MAX_SYMBOLS_PER_CALL)
        try:
            max_symbols = int(max_symbols)
        except (TypeError, ValueError):
            max_symbols = GPT_MAX_SYMBOLS_PER_CALL

        if max_symbols <= 0:
            return summaries

        ranked = sorted(
            summaries,
            key=self._gpt_priority_score,
            reverse=True
        )
        selected = ranked[:max_symbols]
        if len(summaries) > len(selected):
            skipped = [summary.get("code") for summary in ranked[max_symbols:]]
            print("GPT symbol limit skipped:", skipped)
        return selected

    def _gpt_priority_score(self, summary):
        signal = summary.get("validation_signal") or {}
        events = summary.get("events") or []
        try:
            score = float(signal.get("confidence_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        return score + (len(events) * 5.0)

    def _notify_event(self, summary, events, signal, now, skip_reason=None):
        """Send and persist event notifications when the channel cooldown allows it."""
        code = summary.get("code")

        if not self._can_notify(code, now):
            return

        self.notifier.configure(self.settings)

        channels = self._notification_channels(events, signal)

        if not channels:
            return

        results = self.notifier.notify_event(
            summary=summary,
            events=events,
            signal=signal,
            skip_reason=skip_reason,
            channels=channels
        )

        if results:
            message = results[0].get("message")
            self.tick_store.save_notification_logs(
                summary=summary,
                events=events,
                results=results,
                message=message,
                sent_at=now.strftime("%Y-%m-%d %H:%M:%S.%f")
            )
            self.last_notified_at[code] = now

    def _notification_channels(self, events, signal):
        """Keep console broad while making Telegram high-priority only."""
        channels = list(self.settings.get("NOTIFICATION_CHANNELS", []))
        selected = []

        if "console" in channels:
            selected.append("console")

        if "telegram" in channels and self._should_send_telegram_notification(events, signal):
            selected.append("telegram")

        return selected

    def _should_send_telegram_notification(self, events, signal):
        """Return true only for stronger alerts when Telegram filtering is enabled."""
        only_high_priority = self._get_setting(
            "TELEGRAM_NOTIFY_ONLY_HIGH_PRIORITY",
            TELEGRAM_NOTIFY_ONLY_HIGH_PRIORITY
        )

        if not only_high_priority:
            return True

        event_types = {event.get("type") for event in events or []}
        always_notify = set(self._get_setting(
            "TELEGRAM_ALWAYS_NOTIFY_EVENT_TYPES",
            TELEGRAM_ALWAYS_NOTIFY_EVENT_TYPES
        ) or [])

        if event_types & always_notify:
            return True

        if not signal:
            return False

        action_hint = signal.get("action_hint")
        allowed_actions = set(self._get_setting(
            "TELEGRAM_ALLOWED_ACTION_HINTS",
            TELEGRAM_ALLOWED_ACTION_HINTS
        ) or [])

        if action_hint not in allowed_actions:
            return False

        try:
            score = float(signal.get("confidence_score") or 0)
        except (TypeError, ValueError):
            score = 0.0

        min_score = self._get_setting("TELEGRAM_MIN_SIGNAL_SCORE", TELEGRAM_MIN_SIGNAL_SCORE)
        try:
            min_score = float(min_score)
        except (TypeError, ValueError):
            min_score = TELEGRAM_MIN_SIGNAL_SCORE

        return score >= min_score

    def _can_notify(self, code, now):
        """Apply per-symbol notification cooldown."""
        last_notified_at = self.last_notified_at.get(code)

        if not last_notified_at:
            return True

        elapsed_sec = (now - last_notified_at).total_seconds()
        return elapsed_sec >= self._get_setting("NOTIFICATION_COOLDOWN_SEC", 180)

    def _maybe_request_market_context_trs(self, now):
        """Optionally request slower TR-based context.

        Verified mappings are scheduled with a delay between requests so the
        analysis loop does not burst TR calls into Kiwoom.
        """
        if not self._get_setting("ENABLE_KIWOOM_TR_CONTEXT_REQUESTS", False):
            return

        if self.pending_context_tr_requests:
            return

        if self.last_context_tr_requested_at:
            elapsed_sec = (now - self.last_context_tr_requested_at).total_seconds()
            interval_sec = self._get_setting("MARKET_CONTEXT_TR_REQUEST_INTERVAL_SEC", 600)
            if elapsed_sec < interval_sec:
                return

        requests = []
        for code in self.watch_codes.keys():
            for mapping_name in ("short_selling", "stock_loan_trend", "credit", "investor_flow"):
                requests.append((mapping_name, code))

        for mapping_name in (
            "market_investor_flow_kospi",
            "market_investor_flow_kosdaq",
            "market_index_kospi",
            "market_index_kosdaq",
            "market_index_kospi200",
            "fx_usd_krw",
            "market_program_trading",
            "derivatives",
            "option_call_chain",
            "option_put_chain",
        ):
            requests.append((mapping_name, None))

        max_requests = self._get_setting(
            "MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH",
            MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH
        )
        delay_ms = self._get_setting(
            "MARKET_CONTEXT_TR_REQUEST_DELAY_MS",
            MARKET_CONTEXT_TR_REQUEST_DELAY_MS
        )

        try:
            max_requests = int(max_requests)
        except (TypeError, ValueError):
            max_requests = MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH

        try:
            delay_ms = int(delay_ms)
        except (TypeError, ValueError):
            delay_ms = MARKET_CONTEXT_TR_REQUEST_DELAY_MS

        if max_requests > 0:
            requests = requests[:max_requests]

        self.pending_context_tr_requests = list(requests)
        self.context_tr_request_delay_ms = max(delay_ms, 0)
        QTimer.singleShot(0, self._request_next_market_context_mapping)

        print("Scheduled market context TR requests:", len(requests))

        self.last_context_tr_requested_at = now

    def _request_next_market_context_mapping(self):
        """Send TR context requests serially so delayed timers cannot burst."""
        if not self.pending_context_tr_requests:
            return

        request = self.pending_context_tr_requests.pop(0)
        self._request_market_context_mapping(request)

        if self.pending_context_tr_requests:
            QTimer.singleShot(
                self.context_tr_request_delay_ms,
                self._request_next_market_context_mapping
            )

    def _maybe_refresh_macro_context(self, now):
        """Refresh external macro context without blocking the app for long."""
        if not self._get_setting("ENABLE_MACRO_CONTEXT_CRAWL", ENABLE_MACRO_CONTEXT_CRAWL):
            return

        if self.last_macro_context_crawled_at:
            elapsed_sec = (now - self.last_macro_context_crawled_at).total_seconds()
            interval_sec = self._get_setting(
                "MACRO_CONTEXT_REFRESH_INTERVAL_SEC",
                MACRO_CONTEXT_REFRESH_INTERVAL_SEC
            )
            try:
                interval_sec = int(interval_sec)
            except (TypeError, ValueError):
                interval_sec = MACRO_CONTEXT_REFRESH_INTERVAL_SEC

            if elapsed_sec < interval_sec:
                return

        try:
            macro_context = fetch_macro_context(settings=self.settings)
        except Exception as exc:
            macro_context = {
                "asof": now.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "source": "crawler",
                "reliability": "crawler_failed",
                "notes": ["macro context refresh failed: {}".format(exc)],
            }

        self.market_context_store.update_macro_context(macro_context)
        self.market_context_store.update_global_context("data_quality", {
            "macro_context_last_checked_at": macro_context.get(
                "asof",
                now.strftime("%Y-%m-%d %H:%M:%S.%f")
            ),
        })
        self._save_macro_context_snapshot(macro_context, now)
        self.last_macro_context_crawled_at = now
        print("Macro context refreshed:", macro_context.get("reliability"))

    def _save_macro_context_snapshot(self, macro_context, now):
        save_snapshot = getattr(self.tick_store, "save_market_context_snapshot", None)
        if not save_snapshot:
            return

        save_snapshot(
            scope="global",
            code=None,
            section="macro_context",
            payload=macro_context,
            collected_at=macro_context.get("asof") or now.strftime("%Y-%m-%d %H:%M:%S.%f"),
            source=macro_context.get("source") or "crawler",
        )

    def _maybe_refresh_news_context(self, summary, events, signal, now):
        """Fetch low-weight news context only for unusual/problem events."""
        if not self._get_setting("ENABLE_INTRADAY_NEWS_CONTEXT", ENABLE_INTRADAY_NEWS_CONTEXT):
            return

        code = summary.get("code")
        if not code:
            return

        trigger_types = set(self._get_setting(
            "NEWS_CONTEXT_TRIGGER_EVENT_TYPES",
            NEWS_CONTEXT_TRIGGER_EVENT_TYPES
        ) or [])
        event_types = {event.get("type") for event in events or []}

        if not trigger_types.intersection(event_types):
            return

        cooldown_sec = self._get_setting("NEWS_CONTEXT_COOLDOWN_SEC", NEWS_CONTEXT_COOLDOWN_SEC)
        try:
            cooldown_sec = int(cooldown_sec)
        except (TypeError, ValueError):
            cooldown_sec = NEWS_CONTEXT_COOLDOWN_SEC

        last_checked_at = self.last_news_context_checked_at.get(code)
        if last_checked_at and (now - last_checked_at).total_seconds() < cooldown_sec:
            return

        try:
            news_context = fetch_news_context(
                code=code,
                name=summary.get("name"),
                events=events,
                summary=summary,
                settings=self.settings,
            )
        except Exception as exc:
            news_context = {
                "asof": now.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "source": "macro_context_fetcher",
                "reliability": "crawler_failed",
                "weight": "low_intraday",
                "notes": ["news context refresh failed: {}".format(exc)],
            }

        self.market_context_store.update_news(code, news_context)
        self.market_context_store.update_code_context(code, "data_quality", {
            "news_last_checked_at": news_context.get("asof") or now.strftime("%Y-%m-%d %H:%M:%S.%f"),
        })
        self._save_news_context_snapshot(code, news_context, now)
        self.last_news_context_checked_at[code] = now
        print(
            "News context refreshed:",
            code,
            news_context.get("reliability"),
            news_context.get("sentiment"),
            news_context.get("direction_bias"),
        )

    def _save_news_context_snapshot(self, code, news_context, now):
        save_snapshot = getattr(self.tick_store, "save_market_context_snapshot", None)
        if not save_snapshot:
            return

        save_snapshot(
            scope="code",
            code=code,
            section="news",
            payload=news_context,
            collected_at=news_context.get("asof") or now.strftime("%Y-%m-%d %H:%M:%S.%f"),
            source=news_context.get("source") or "crawler",
            reliability=news_context.get("reliability"),
            weight=news_context.get("weight"),
            summary=news_context.get("summary"),
        )

    def _maybe_save_market_status_snapshot(self, now):
        """Persist manual market-wide interruption updates when they change."""
        if not self.tick_store.conn:
            return

        context = self.market_context_store.get_context(None)
        market_status = context.get("market_status") or {}
        key = (
            market_status.get("asof"),
            market_status.get("market"),
            market_status.get("sidecar_status"),
            market_status.get("sidecar_direction"),
            market_status.get("sidecar_started_at"),
            market_status.get("sidecar_ended_at"),
            market_status.get("circuit_breaker_status"),
            market_status.get("vi_status"),
        )

        if key == self.last_market_status_snapshot_key:
            return

        has_abnormal_status = any([
            market_status.get("sidecar_status") not in (None, "", "inactive"),
            market_status.get("circuit_breaker_status") not in (None, "", "inactive"),
            market_status.get("vi_status") not in (None, "", "inactive"),
        ])

        if not has_abnormal_status:
            self.last_market_status_snapshot_key = key
            return

        self.tick_store.save_market_context_snapshot(
            scope="global",
            code=None,
            section="market_status",
            payload=market_status,
            collected_at=market_status.get("asof") or now.strftime("%Y-%m-%d %H:%M:%S.%f"),
            source=market_status.get("source") or "manual",
            reliability=market_status.get("reliability"),
            summary=market_status.get("summary"),
        )
        self.market_context_store.update_global_context("data_quality", {
            "market_status_last_checked_at": market_status.get("asof") or now.strftime("%Y-%m-%d %H:%M:%S.%f"),
        })
        self.last_market_status_snapshot_key = key
        print("Market status snapshot saved:", market_status.get("summary"))

    def _request_market_context_mapping(self, request):
        """Send one delayed market-context TR request."""
        mapping_name, code = request
        try:
            result = self.kiwoom.request_context_mapping(mapping_name, code=code)
            print("시장 컨텍스트 TR 요청:", mapping_name, code or "global", result)
        except ValueError as exc:
            print("시장 컨텍스트 TR 요청 생략:", exc)

    def _preload_recent_ticks(self):
        """Warm-start in-memory indicators from recent SQLite ticks."""
        if not self._get_setting("PRELOAD_RECENT_TICKS_FROM_DB", True):
            return

        loaded_counts = self.tick_store.preload_recent_ticks_from_db(
            codes=self._get_realtime_codes(),
            limit_per_code=self._get_setting("PRELOAD_TICKS_PER_CODE", PRELOAD_TICKS_PER_CODE),
            max_age_minutes=self._get_setting(
                "PRELOAD_TICKS_MAX_AGE_MINUTES",
                PRELOAD_TICKS_MAX_AGE_MINUTES
            )
        )

        if loaded_counts:
            print("Preloaded recent ticks:", loaded_counts)

    def _reload_runtime_settings(self):
        """Reload DB settings and apply runtime-safe changes."""
        self.settings = self.settings_store.get_runtime_settings()
        interval_sec = self._get_setting("GPT_ANALYSIS_INTERVAL_SEC", GPT_ANALYSIS_INTERVAL_SEC)
        watch_codes = self._normalize_watch_codes(self._get_setting("WATCH_CODES", WATCH_CODES))
        market_benchmark_codes = self._normalize_watch_codes(
            self._get_setting("MARKET_BENCHMARK_CODES", MARKET_BENCHMARK_CODES)
        )

        if interval_sec <= 0:
            interval_sec = GPT_ANALYSIS_INTERVAL_SEC

        if interval_sec != self.current_timer_interval_sec:
            self.current_timer_interval_sec = interval_sec
            self.timer.setInterval(interval_sec * 1000)
            print("Analysis interval updated:", interval_sec, "sec")

        realtime_codes_changed = (
            watch_codes != self.watch_codes
            or market_benchmark_codes != self.market_benchmark_codes
        )

        if watch_codes != self.watch_codes:
            self.watch_codes = watch_codes
            self.last_gpt_called_at = {
                code: value
                for code, value in self.last_gpt_called_at.items()
                if code in self.watch_codes
            }
            self.last_notified_at = {
                code: value
                for code, value in self.last_notified_at.items()
                if code in self.watch_codes
            }
            print("Watch codes updated:", self.watch_codes)

        if market_benchmark_codes != self.market_benchmark_codes:
            self.market_benchmark_codes = market_benchmark_codes
            print("Market benchmark codes updated:", self.market_benchmark_codes)

        if realtime_codes_changed:
            self.kiwoom.update_realtime_codes(self._get_realtime_codes())

    def _get_realtime_codes(self):
        """Return analysis symbols plus context-only benchmark ETFs."""
        return list(dict.fromkeys(
            list(self.watch_codes.keys()) + list(self.market_benchmark_codes.keys())
        ))

    def _update_benchmark_etf_context(self):
        """Attach compact ETF snapshots to the global GPT market context."""
        snapshots = {}

        for code, name in self.market_benchmark_codes.items():
            ticks = self.tick_store.get_recent_ticks(code)
            snapshot = make_market_snapshot(ticks)

            if snapshot:
                timeframe_summary = summarize_multi_timeframes_for_gpt(
                    code=code,
                    name=name,
                    ticks=ticks,
                    drop_last=True
                )
                snapshots[code] = {
                    "name": name,
                    "snapshot": snapshot,
                }
                if timeframe_summary:
                    snapshots[code]["timeframes"] = timeframe_summary.get("timeframes")

        self.market_context_store.update_global_context("benchmark_etfs", snapshots)


    def _get_setting(self, key, default):
        return self.settings.get(key, default)

    def _normalize_watch_codes(self, watch_codes):
        """Normalize watch code settings loaded from JSON."""
        normalized = {}

        for code, name in (watch_codes or {}).items():
            code = str(code).strip()
            name = str(name).strip()

            if code:
                normalized[code] = name or code

        return normalized


if __name__ == "__main__":
    app = QApplication(sys.argv)
    strategy_app = RealtimeStrategyApp()
    sys.exit(app.exec_())
