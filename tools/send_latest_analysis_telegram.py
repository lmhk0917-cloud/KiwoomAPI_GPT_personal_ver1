"""Send a Telegram message from the latest saved analysis row."""

import argparse
import json
import sqlite3
from datetime import datetime

from app_paths import DEFAULT_DB_PATH
from data_store import TickStore
from notifier import Notifier


def main():
    args = parse_args()
    store = TickStore(db_path=args.db)
    try:
        payload = fetch_latest_payload(store.conn, args.analysis_id)
        if not payload:
            raise SystemExit("No analysis row found.")

        notifier = Notifier(settings={
            "ENABLE_NOTIFICATIONS": True,
            "NOTIFICATION_CHANNELS": ["telegram"],
        })

        message = build_message(payload, args.max_gpt_chars)
        results = notifier.notify_text(message, channels=["telegram"])

        store.save_notification_logs(
            summary=payload["summary"],
            events=payload["events"],
            results=results,
            message=message,
            sent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        )

        print(json.dumps(results, ensure_ascii=False, indent=2))
        failed = [r for r in results if r.get("status") not in ("success", "skipped")]
        return 1 if failed else 0
    finally:
        store.close()


def fetch_latest_payload(conn, analysis_id=None):
    if analysis_id is None:
        row = conn.execute("""
            select *
            from analysis_results
            order by id desc
            limit 1
        """).fetchone()
    else:
        row = conn.execute("""
            select *
            from analysis_results
            where id = ?
        """, (analysis_id,)).fetchone()

    if not row:
        return None

    summary = json.loads(row["summary_json"]) if row["summary_json"] else {}
    code = row["code"]
    analyzed_at = row["analyzed_at"]

    events = conn.execute("""
        select event_type, timeframe, message, value
        from event_logs
        where code = ?
        order by id desc
        limit 5
    """, (code,)).fetchall()

    signal = conn.execute("""
        select action_hint, confidence_score, risk_level, current_price,
               stop_loss, target_1, target_2
        from signal_logs
        where code = ?
        order by id desc
        limit 1
    """, (code,)).fetchone()

    return {
        "row": row,
        "summary": summary,
        "events": [
            {
                "type": event["event_type"],
                "timeframe": event["timeframe"],
                "message": event["message"],
                "value": event["value"],
            }
            for event in events
        ],
        "signal": dict(signal) if signal else None,
        "analyzed_at": analyzed_at,
    }


def build_message(payload, max_gpt_chars):
    row = payload["row"]
    summary = payload["summary"]
    signal = payload["signal"] or {}
    events = payload["events"]
    event_text = ", ".join(event.get("type") or "UNKNOWN" for event in events) or "없음"
    gpt_result = row["gpt_result"] or ""

    if len(gpt_result) > max_gpt_chars:
        gpt_result = gpt_result[:max_gpt_chars].rstrip() + "\n...[일부 생략]"

    return "\n".join([
        "[저장 데이터 GPT 분석 테스트]",
        "분석시각: {}".format(payload["analyzed_at"]),
        "종목: {} ({})".format(row["name"], row["code"]),
        "현재가: {}".format(row["current_price"]),
        "RSI14: {}".format(row["rsi14"]),
        "거래량 배율(20봉): {}".format(row["volume_ratio_20"]),
        "VWAP 거리(%): {}".format(row["vwap_distance_pct"]),
        "최근 이벤트: {}".format(event_text),
        "판단 신호: {} / 점수={} / 위험도={}".format(
            signal.get("action_hint", "없음"),
            signal.get("confidence_score", "없음"),
            signal.get("risk_level", "없음"),
        ),
        "",
        "[GPT 분석 결과]",
        gpt_result,
    ])


def parse_args():
    parser = argparse.ArgumentParser(description="Send latest saved analysis over Telegram.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--analysis-id", type=int)
    parser.add_argument("--max-gpt-chars", type=int, default=1800)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
