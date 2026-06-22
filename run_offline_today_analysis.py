"""Build analysis, signals, GPT review, and paper feedback from saved ticks.

This is a recovery path for days when the tick-only collector ran without the
full realtime analysis loop. It reads persisted ticks only; it does not log in,
request Kiwoom TRs, send notifications, or place orders.
"""

import argparse
import json
import os
from datetime import datetime, timedelta

from app_paths import DEFAULT_DB_PATH, setup_runtime_logging
from config import WATCH_CODES
from data_store import TickStore
from env_loader import load_project_env
from event_detector import detect_gpt_events
from gpt_analyzer import GPTAnalyzer
from gpt_result_parser import parse_gpt_analysis_scores
from indicators import summarize_multi_timeframes_for_gpt
from market_context import MarketContextStore
from paper_trade_simulator import evaluate_signal, fetch_pending_signals
from settings_store import SettingsStore
from signal_generator import generate_validation_signal


def main():
    args = parse_args()
    setup_runtime_logging("offline_today_analysis")
    load_project_env()

    codes = parse_codes(args.codes)
    store = TickStore(db_path=args.db)
    settings = SettingsStore(conn=store.conn).get_runtime_settings()
    context_store = MarketContextStore()
    context_store.reload()

    try:
        if existing_today_analysis(store, args.date) and not args.force:
            raise SystemExit(
                "analysis_results already exist for {}. Use --force to append another run.".format(
                    args.date
                )
            )

        all_ticks = {code: fetch_ticks_for_date(store, code, args.date) for code in codes}
        latest_summaries = []
        total_events = 0
        total_signals = 0

        for code in codes:
            ticks = all_ticks.get(code) or []
            name = WATCH_CODES.get(code, code)
            if len(ticks) < args.min_ticks:
                print("OFFLINE_SKIP code={} reason=not_enough_ticks count={}".format(code, len(ticks)))
                continue

            cutoffs = build_cutoffs(ticks, sample_minutes=args.sample_minutes)
            for cutoff in cutoffs:
                sample = ticks_until(ticks, cutoff)
                summary = build_summary(
                    code=code,
                    name=name,
                    ticks=sample,
                    detected_at=cutoff.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    context=context_store.get_context(code),
                    settings=settings,
                )
                if not summary:
                    continue
                events = summary.get("events") or []
                if events:
                    store.save_event_logs(
                        summary=summary,
                        events=events,
                        detected_at=summary["detected_at"],
                        gpt_requested=False,
                        skip_reason="offline_historical_sample",
                    )
                    total_events += len(events)
                    signal = generate_validation_signal(summary, settings=settings)
                    if signal:
                        summary["validation_signal"] = signal
                        store.save_signal_log(
                            signal=signal,
                            summary=summary,
                            detected_at=summary["detected_at"],
                        )
                        total_signals += 1

            latest = build_summary(
                code=code,
                name=name,
                ticks=ticks,
                detected_at=args.date + " 15:30:00.000000",
                context=context_store.get_context(code),
                settings=settings,
            )
            if latest:
                latest_summaries.append(latest)

        gpt_result = run_gpt_review(store, latest_summaries, settings, args)
        saved_analysis = 0
        analyzed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        for summary in latest_summaries:
            store.save_analysis_result(
                summary=summary,
                gpt_result=gpt_result,
                analyzed_at=analyzed_at,
            )
            saved_analysis += 1

        evaluated = evaluate_today_paper(store, args.date, args.paper_limit)

        print("========== Offline Today Analysis ==========")
        print("date:", args.date)
        print("codes:", ",".join(codes))
        print("tick_counts:", json.dumps({code: len(all_ticks.get(code) or []) for code in codes}, ensure_ascii=False))
        print("saved_events:", total_events)
        print("saved_signals:", total_signals)
        print("saved_analysis_results:", saved_analysis)
        print("evaluated_paper_trades:", evaluated)
        print("gpt_enabled:", bool(args.gpt))
        print("gpt_result_chars:", len(gpt_result or ""))
        print()
        print((gpt_result or "")[:4000])
    finally:
        store.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Recover today's analysis from saved ticks.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--codes", default=",".join(WATCH_CODES.keys()))
    parser.add_argument("--sample-minutes", type=int, default=30)
    parser.add_argument("--min-ticks", type=int, default=200)
    parser.add_argument("--paper-limit", type=int, default=200)
    parser.add_argument("--gpt", action="store_true", help="Call GPT for final risk/reward review.")
    parser.add_argument("--force", action="store_true", help="Append another offline analysis even if rows exist.")
    return parser.parse_args()


def parse_codes(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def existing_today_analysis(store, date_text):
    row = store.conn.execute(
        "SELECT COUNT(*) FROM analysis_results WHERE analyzed_at LIKE ?",
        (date_text + "%",),
    ).fetchone()
    return bool(row and row[0])


def fetch_ticks_for_date(store, code, date_text):
    rows = store.conn.execute(
        """
        SELECT code, trade_time, price, change_rate, acc_volume, tick_volume,
               open_price, high_price, low_price, strength, received_at
        FROM ticks
        WHERE code = ?
          AND received_at LIKE ?
        ORDER BY received_at ASC
        """,
        (code, date_text + "%"),
    ).fetchall()
    return [dict(row) for row in rows]


def build_cutoffs(ticks, sample_minutes):
    first_dt = parse_dt(ticks[0]["received_at"])
    last_dt = parse_dt(ticks[-1]["received_at"])
    if not first_dt or not last_dt:
        return []
    cursor = first_dt.replace(second=0, microsecond=0) + timedelta(minutes=sample_minutes)
    cutoffs = []
    while cursor < last_dt - timedelta(minutes=65):
        cutoffs.append(cursor)
        cursor += timedelta(minutes=sample_minutes)
    return cutoffs


def ticks_until(ticks, cutoff):
    cutoff_text = cutoff.strftime("%Y-%m-%d %H:%M:%S.%f")
    return [tick for tick in ticks if tick.get("received_at") <= cutoff_text]


def build_summary(code, name, ticks, detected_at, context, settings):
    summary = summarize_multi_timeframes_for_gpt(
        code=code,
        name=name,
        ticks=ticks,
        drop_last=True,
    )
    if not summary:
        return None
    summary["detected_at"] = detected_at
    summary["market_context"] = context
    events = detect_gpt_events(summary, settings=settings)
    summary["events"] = events
    signal = generate_validation_signal(summary, settings=settings) if events else None
    if signal:
        summary["validation_signal"] = signal
    return summary


def run_gpt_review(store, summaries, settings, args):
    if not summaries:
        return "No offline summaries were generated."
    if not args.gpt:
        return "GPT review skipped; offline deterministic summary saved."

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "GPT review skipped; OPENAI_API_KEY is not configured."

    gpt = GPTAnalyzer(api_key=api_key)
    started_at = datetime.now()
    result = gpt.analyze(summaries, settings=settings)
    finished_at = datetime.now()
    payload_stats = gpt.last_payload_stats or {}
    status = "failed" if gpt.last_error_message else "success"

    gpt_call_id = store.save_gpt_call_log(
        started_at=started_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        finished_at=finished_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        status=status,
        requested_count=len(summaries),
        codes=[summary["code"] for summary in summaries],
        model=gpt.last_model,
        duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        prompt_chars=gpt.last_prompt_chars,
        payload_original_chars=payload_stats.get("original_json_chars"),
        payload_compressed_chars=payload_stats.get("compressed_json_chars"),
        payload_compression_ratio=payload_stats.get("compression_ratio"),
        prompt_tokens=gpt.last_usage.get("prompt_tokens"),
        completion_tokens=gpt.last_usage.get("completion_tokens"),
        total_tokens=gpt.last_usage.get("total_tokens"),
        error_message=gpt.last_error_message,
        result_preview=result[:500] if result else None,
    )
    score_rows = parse_gpt_analysis_scores(
        result_text=result,
        summaries=summaries,
        gpt_call_id=gpt_call_id,
        analyzed_at=finished_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
    )
    store.save_gpt_analysis_scores(score_rows)
    return result


def evaluate_today_paper(store, date_text, limit):
    signals = fetch_pending_signals(
        store=store,
        limit=limit,
        since=date_text + " 00:00:00",
    )
    evaluated = 0
    for signal in signals:
        result = evaluate_signal(store, signal, allow_partial=True)
        if result:
            store.save_paper_trade_result(result)
            evaluated += 1
    return evaluated


def parse_dt(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


if __name__ == "__main__":
    raise SystemExit(main())
