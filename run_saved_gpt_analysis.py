"""Call GPT using previously saved analysis_results rows.

This script is useful outside market hours: it replays collected market data
from SQLite into the current GPT prompt/compression pipeline, logs the API
call, and optionally saves the returned analysis text for UI review.
"""

import argparse
import json
import os
from datetime import datetime

from app_paths import DEFAULT_DB_PATH, setup_runtime_logging
from data_store import TickStore
from env_loader import load_project_env
from gpt_analyzer import GPTAnalyzer
from settings_store import SettingsStore


def main():
    args = parse_args()
    setup_runtime_logging("run_saved_gpt_analysis")
    load_project_env()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not configured in .env")

    store = TickStore(db_path=args.db)
    settings_store = SettingsStore(conn=store.conn)
    settings = settings_store.get_runtime_settings()

    try:
        rows = fetch_saved_summaries(
            conn=store.conn,
            analysis_id=args.analysis_id,
            code=args.code,
            limit=args.limit
        )

        if not rows:
            raise SystemExit("No saved analysis rows found.")

        summaries = [json.loads(row["summary_json"]) for row in rows if row["summary_json"]]
        codes = [summary.get("code") for summary in summaries]

        gpt = GPTAnalyzer(api_key=api_key)
        started_at = datetime.now()
        result = gpt.analyze(summaries, settings=settings)
        finished_at = datetime.now()

        status = "failed" if gpt.last_error_message else "success"
        payload_stats = gpt.last_payload_stats or {}

        store.save_gpt_call_log(
            started_at=started_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            finished_at=finished_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            status=status,
            requested_count=len(summaries),
            codes=codes,
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
            result_preview=result[:500] if result else None
        )

        if args.save_analysis_result:
            saved_at = finished_at.strftime("%Y-%m-%d %H:%M:%S.%f")
            for summary in summaries:
                store.save_analysis_result(
                    summary=summary,
                    gpt_result=result,
                    analyzed_at=saved_at
                )

        print("========== Saved GPT Analysis Run ==========")
        print("db:", args.db)
        print("source_analysis_ids:", ",".join(str(row["id"]) for row in rows))
        print("codes:", ",".join(str(code) for code in codes))
        print("status:", status)
        print("model:", gpt.last_model)
        print("duration_ms:", int((finished_at - started_at).total_seconds() * 1000))
        print("prompt_chars:", gpt.last_prompt_chars)
        print("payload_original_chars:", payload_stats.get("original_json_chars"))
        print("payload_compressed_chars:", payload_stats.get("compressed_json_chars"))
        print("payload_compression_ratio:", payload_stats.get("compression_ratio"))
        print("prompt_tokens:", gpt.last_usage.get("prompt_tokens"))
        print("completion_tokens:", gpt.last_usage.get("completion_tokens"))
        print("total_tokens:", gpt.last_usage.get("total_tokens"))
        print("saved_analysis_result:", bool(args.save_analysis_result))
        print()
        print(result)
    finally:
        store.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Replay saved analysis data through GPT.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--analysis-id", type=int, help="Specific analysis_results.id to replay")
    parser.add_argument("--code", help="Optional stock code filter when --analysis-id is omitted")
    parser.add_argument("--limit", type=int, default=1, help="Recent saved rows to replay")
    parser.add_argument(
        "--save-analysis-result",
        action="store_true",
        help="Save the GPT response as new analysis_results rows for dashboard review"
    )
    return parser.parse_args()


def fetch_saved_summaries(conn, analysis_id=None, code=None, limit=1):
    if analysis_id is not None:
        return conn.execute("""
            SELECT id, analyzed_at, code, name, summary_json
            FROM analysis_results
            WHERE id = ?
        """, (analysis_id,)).fetchall()

    where = ""
    params = []
    if code:
        where = "WHERE code = ?"
        params.append(code)

    params.append(limit)
    return conn.execute("""
        SELECT id, analyzed_at, code, name, summary_json
        FROM analysis_results
        {}
        ORDER BY analyzed_at DESC
        LIMIT ?
    """.format(where), params).fetchall()


if __name__ == "__main__":
    main()
