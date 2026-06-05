"""Readable GPT API call history report.

The realtime app stores each GPT request in ``gpt_call_logs``. This script
prints a compact audit view so the user can check when GPT was called, for
which symbols, whether it failed, and how many tokens were used when the SDK
returned usage metadata.
"""

import argparse
import json
from datetime import datetime, timedelta

from app_paths import DEFAULT_DB_PATH
from data_store import TickStore


def main():
    args = parse_args()
    store = TickStore(db_path=args.db)

    try:
        report = build_report(
            conn=store.conn,
            limit=args.limit,
            days=args.days,
            status=args.status,
            code=args.code,
        )
    finally:
        store.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)


def parse_args():
    parser = argparse.ArgumentParser(description="Show GPT API call history.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--limit", type=int, default=20, help="Recent call rows to show")
    parser.add_argument("--days", type=int, help="Only include calls from the latest N days")
    parser.add_argument("--status", choices=["success", "failed", "simulated"], help="Optional status filter")
    parser.add_argument("--code", help="Optional stock code filter")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    return parser.parse_args()


def build_report(conn, limit=20, days=None, status=None, code=None):
    where_sql, params = make_where_clause(days=days, status=status, code=code)
    overview = fetch_overview(conn, where_sql, params)
    rows = fetch_recent_calls(conn, where_sql, params, limit=limit)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "filters": {
            "limit": limit,
            "days": days,
            "status": status,
            "code": code,
        },
        "overview": row_to_dict(overview),
        "recent_calls": [row_to_dict(row) for row in rows],
    }


def make_where_clause(days=None, status=None, code=None):
    clauses = []
    params = []

    if days:
        since = datetime.now() - timedelta(days=days)
        clauses.append("started_at >= ?")
        params.append(since.strftime("%Y-%m-%d %H:%M:%S.%f"))

    if status:
        clauses.append("status = ?")
        params.append(status)

    if code:
        clauses.append("codes LIKE ?")
        params.append("%{}%".format(code))

    if not clauses:
        return "", params

    return "WHERE " + " AND ".join(clauses), params


def fetch_overview(conn, where_sql, params):
    sql = """
        SELECT
            COUNT(1) AS call_count,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
            SUM(CASE WHEN status = 'simulated' THEN 1 ELSE 0 END) AS simulated_count,
            MIN(started_at) AS first_started_at,
            MAX(started_at) AS latest_started_at,
            ROUND(AVG(duration_ms), 1) AS avg_duration_ms,
            ROUND(AVG(prompt_chars), 1) AS avg_prompt_chars,
            ROUND(AVG(payload_original_chars), 1) AS avg_payload_original_chars,
            ROUND(AVG(payload_compressed_chars), 1) AS avg_payload_compressed_chars,
            ROUND(AVG(payload_compression_ratio), 4) AS avg_payload_compression_ratio,
            SUM(prompt_tokens) AS prompt_tokens,
            SUM(completion_tokens) AS completion_tokens,
            SUM(total_tokens) AS total_tokens,
            SUM(CASE WHEN total_tokens IS NULL THEN 1 ELSE 0 END) AS legacy_or_missing_usage_count
        FROM gpt_call_logs
        {where_sql}
    """.format(where_sql=where_sql)
    return conn.execute(sql, params).fetchone()


def fetch_recent_calls(conn, where_sql, params, limit):
    sql = """
        SELECT
            id,
            started_at,
            finished_at,
            status,
            requested_count,
            codes,
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
            result_preview
        FROM gpt_call_logs
        {where_sql}
        ORDER BY id DESC
        LIMIT ?
    """.format(where_sql=where_sql)
    return conn.execute(sql, params + [limit]).fetchall()


def row_to_dict(row):
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def parse_codes(raw_codes):
    if not raw_codes:
        return []

    try:
        value = json.loads(raw_codes)
        if isinstance(value, list):
            return value
    except (TypeError, ValueError):
        pass

    return [raw_codes]


def print_text_report(report):
    overview = report["overview"]
    filters = report["filters"]

    print("========== GPT Call History ==========")
    print("generated_at:", report["generated_at"])
    print(
        "filters: limit={limit}, days={days}, status={status}, code={code}"
        .format(**filters)
    )
    print()

    print("[Overview]")
    print(
        "calls={calls}, success={success}, failed={failed}, simulated={simulated}, "
        "avg_duration_ms={duration}"
        .format(
            calls=overview.get("call_count") or 0,
            success=overview.get("success_count") or 0,
            failed=overview.get("failed_count") or 0,
            simulated=overview.get("simulated_count") or 0,
            duration=overview.get("avg_duration_ms"),
        )
    )
    print(
        "tokens: prompt={prompt}, completion={completion}, total={total}, missing_usage_rows={missing}"
        .format(
            prompt=overview.get("prompt_tokens") or 0,
            completion=overview.get("completion_tokens") or 0,
            total=overview.get("total_tokens") or 0,
            missing=overview.get("legacy_or_missing_usage_count") or 0,
        )
    )
    print(
        "payload: avg_prompt_chars={prompt_chars}, avg_original_chars={original}, "
        "avg_compressed_chars={compressed}, avg_ratio={ratio}"
        .format(
            prompt_chars=overview.get("avg_prompt_chars"),
            original=overview.get("avg_payload_original_chars"),
            compressed=overview.get("avg_payload_compressed_chars"),
            ratio=overview.get("avg_payload_compression_ratio"),
        )
    )
    print("first_started:", overview.get("first_started_at"))
    print("latest_started:", overview.get("latest_started_at"))
    print()

    print("[Recent Calls]")
    if not report["recent_calls"]:
        print("  no rows")
        return

    for item in report["recent_calls"]:
        codes = ",".join(str(code) for code in parse_codes(item.get("codes")))
        preview = item.get("result_preview") or ""
        preview = preview.replace("\r", " ").replace("\n", " ")
        if len(preview) > 180:
            preview = preview[:180] + "..."

        print("-" * 80)
        print(
            "id={id} started={started} status={status} model={model} duration_ms={duration}"
            .format(
                id=item.get("id"),
                started=item.get("started_at"),
                status=item.get("status"),
                model=item.get("model") or "(legacy)",
                duration=item.get("duration_ms"),
            )
        )
        print(
            "requested_count={count} codes={codes} tokens={tokens} prompt={prompt} completion={completion}"
            .format(
                count=item.get("requested_count"),
                codes=codes,
                tokens=item.get("total_tokens"),
                prompt=item.get("prompt_tokens"),
                completion=item.get("completion_tokens"),
            )
        )
        print(
            "chars: prompt={prompt_chars} original_payload={original} compressed_payload={compressed} ratio={ratio}"
            .format(
                prompt_chars=item.get("prompt_chars"),
                original=item.get("payload_original_chars"),
                compressed=item.get("payload_compressed_chars"),
                ratio=item.get("payload_compression_ratio"),
            )
        )
        if item.get("error_message"):
            print("error:", item.get("error_message"))
        print("preview:", preview)


if __name__ == "__main__":
    main()
