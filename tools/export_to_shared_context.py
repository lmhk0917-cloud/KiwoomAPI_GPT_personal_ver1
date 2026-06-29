"""Export sanitized Kiwoom Core summaries into the shared market context hub."""

import json
import os
import sqlite3
import sys
from datetime import datetime


KIWOOM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED_ROOT = r"C:\Users\lmhk2\Documents\New project\shared_market_context"
if SHARED_ROOT not in sys.path:
    sys.path.insert(0, SHARED_ROOT)

from shared_context_store import SharedContextStore

try:
    from app_paths import DEFAULT_DB_PATH
except ImportError:  # pragma: no cover
    DEFAULT_DB_PATH = os.path.join(KIWOOM_ROOT, "data", "ticks.db")


DEFAULT_SHARED_DB = os.path.join(SHARED_ROOT, "shared_context.db")
MARKET_CONTEXT_PATH = os.path.join(KIWOOM_ROOT, "market_context.json")


def main(argv=None):
    db_path = os.environ.get("KIWOOM_CORE_DB_PATH") or DEFAULT_DB_PATH
    shared_db = os.environ.get("SHARED_CONTEXT_DB_PATH") or DEFAULT_SHARED_DB
    rows = export_to_shared_context(db_path=db_path, shared_db=shared_db)
    json_status = refresh_latest_json(shared_db)
    print("KIWOOM_SHARED_CONTEXT_EXPORT_STATUS=ok")
    print("KIWOOM_SHARED_CONTEXT_EXPORT_ROWS={}".format(rows))
    print("KIWOOM_SHARED_CONTEXT_DB={}".format(shared_db))
    print("KIWOOM_SHARED_CONTEXT_JSON_EXPORT_STATUS={}".format(json_status))
    return 0


def export_to_shared_context(db_path=None, shared_db=DEFAULT_SHARED_DB, market_context_path=MARKET_CONTEXT_PATH):
    db_path = db_path or DEFAULT_DB_PATH
    store = SharedContextStore(db_path=shared_db)
    row_count = 0
    try:
        row_count += _export_market_context_json(store, market_context_path)
        if not os.path.exists(db_path):
            store.insert_snapshot(
                "kiwoom", "KR", None, "context", "runtime_status",
                {"status": "missing", "db_path": db_path},
                status="missing",
            )
            return row_count + 1
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row_count += _export_market_context_snapshots(conn, store)
            row_count += _export_tick_minute_summaries(conn, store)
        finally:
            conn.close()
        return row_count
    finally:
        store.close()


def _export_market_context_json(store, path):
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    collected_at = payload.get("asof") or _now()
    count = 0
    for section, body in (payload.get("global") or payload).items():
        if not isinstance(body, (dict, list)):
            continue
        store.insert_snapshot(
            "kiwoom",
            "KR",
            None,
            "context",
            section,
            body,
            asof=(body.get("asof") if isinstance(body, dict) else None) or payload.get("asof"),
            collected_at=collected_at,
            sample_count=1,
        )
        count += 1
    return count


def _export_market_context_snapshots(conn, store):
    if not _has_table(conn, "market_context_snapshots"):
        return 0
    rows = conn.execute("""
        SELECT m.*
        FROM market_context_snapshots m
        JOIN (
            SELECT scope, COALESCE(code, '') AS code_key, section, MAX(id) AS latest_id
            FROM market_context_snapshots
            GROUP BY scope, COALESCE(code, ''), section
        ) latest ON latest.latest_id = m.id
        ORDER BY m.section, m.code
    """).fetchall()
    count = 0
    for row in rows:
        payload = _parse_json(row["payload_json"])
        store.insert_snapshot(
            "kiwoom",
            "KR",
            row["code"],
            "context",
            row["section"],
            {
                "scope": row["scope"],
                "source": row["source"],
                "reliability": row["reliability"],
                "weight": row["weight"],
                "summary": row["summary"],
                "payload": payload,
            },
            asof=row["asof"],
            collected_at=row["collected_at"],
            sample_count=1,
        )
        count += 1
    return count


def _export_tick_minute_summaries(conn, store):
    if not _has_table(conn, "ticks"):
        return 0
    rows = conn.execute("""
        SELECT code,
               COUNT(1) AS sample_count,
               MAX(received_at) AS latest_tick_timestamp,
               MIN(received_at) AS oldest_tick_timestamp,
               MIN(price) AS min_price,
               MAX(price) AS max_price,
               AVG(price) AS avg_price,
               SUM(COALESCE(tick_volume, 0)) AS tick_volume_sum
        FROM ticks
        WHERE received_at >= datetime('now', '-1 day')
        GROUP BY code
        ORDER BY code
    """).fetchall()
    if not rows:
        return 0
    latest = max(row["latest_tick_timestamp"] for row in rows if row["latest_tick_timestamp"])
    store.insert_snapshot(
        "kiwoom",
        "KR",
        None,
        "minute",
        "domestic_tick_minute_summary",
        {"rows": [dict(row) for row in rows]},
        asof=latest,
        collected_at=_now(),
        sample_count=sum(int(row["sample_count"] or 0) for row in rows),
    )
    return 1


def _has_table(conn, table):
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _parse_json(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def refresh_latest_json(shared_db):
    try:
        from export_latest_json import export_all

        export_all(db_path=shared_db)
        return "ok"
    except Exception as exc:
        print("KIWOOM_SHARED_CONTEXT_JSON_EXPORT_ERROR={}".format(exc))
        return "failed"


if __name__ == "__main__":
    raise SystemExit(main())
