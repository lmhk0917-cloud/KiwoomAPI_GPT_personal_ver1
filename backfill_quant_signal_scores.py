"""Backfill deterministic quant score rows for existing saved signals.

This is an audit/backtest helper. It does not place orders or alter live
collection behavior. By default it only fills quant_signal_scores for signal_logs
rows that do not already have a quant score. With --refresh-existing it updates
existing score rows in place so feature_json can be rebuilt after formula
changes without duplicating signal_id rows.
"""

import argparse
import json
from datetime import datetime, timedelta

from app_paths import DEFAULT_DB_PATH
from data_store import TickStore
from quant_signal_score import build_quant_signal_score


def main():
    args = parse_args()
    store = TickStore(db_path=args.db)
    try:
        result = backfill_quant_signal_scores(
            conn=store.conn,
            store=store,
            days=args.days,
            code=args.code,
            limit=args.limit,
            dry_run=args.dry_run,
            refresh_existing=args.refresh_existing,
        )
    finally:
        store.close()

    print("========== Quant Signal Score Backfill ==========")
    print("db:", args.db)
    print("days:", args.days)
    print("code:", args.code or "ALL")
    print("limit:", args.limit or "none")
    print("dry_run:", args.dry_run)
    print("refresh_existing:", args.refresh_existing)
    print("candidates:", result["candidates"])
    print("inserted:", result["inserted"])
    print("updated:", result["updated"])
    print("skipped:", result["skipped"])
    if result.get("first_signal_id") is not None:
        print("first_signal_id:", result["first_signal_id"])
        print("last_signal_id:", result["last_signal_id"])


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill quant_signal_scores from signal_logs.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--days", type=int, default=5, help="Only include signals from the last N days. Use 0 for all.")
    parser.add_argument("--code", help="Optional symbol filter.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to backfill. Use 0 for no limit.")
    parser.add_argument("--dry-run", action="store_true", help="Count candidates without inserting rows.")
    parser.add_argument("--refresh-existing", action="store_true", help="Update existing quant_signal_scores rows instead of only filling missing rows.")
    return parser.parse_args()


def backfill_quant_signal_scores(conn, store, days=5, code=None, limit=0, dry_run=False, refresh_existing=False):
    rows = fetch_quant_score_signals(
        conn,
        days=days,
        code=code,
        limit=limit,
        refresh_existing=refresh_existing,
    )
    inserted = 0
    updated = 0
    skipped = 0
    first_signal_id = rows[0]["id"] if rows else None
    last_signal_id = rows[-1]["id"] if rows else None

    for row in rows:
        summary = _load_json(row["summary_json"])
        if not summary:
            skipped += 1
            continue
        signal = _signal_from_row(row)
        score = build_quant_signal_score(
            signal=signal,
            summary=summary,
            signal_id=row["id"],
            scored_at=row["detected_at"],
        )
        if dry_run:
            if row["quant_score_id"] is None:
                inserted += 1
            else:
                updated += 1
            continue
        if row["quant_score_id"] is not None:
            updated += update_quant_signal_score(conn, row["quant_score_id"], score)
        else:
            saved_id = store.save_quant_signal_score(score)
            if saved_id is None:
                skipped += 1
            else:
                inserted += 1

    return {
        "candidates": len(rows),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "first_signal_id": first_signal_id,
        "last_signal_id": last_signal_id,
    }


def fetch_missing_quant_score_signals(conn, days=5, code=None, limit=0):
    return fetch_quant_score_signals(
        conn,
        days=days,
        code=code,
        limit=limit,
        refresh_existing=False,
    )


def fetch_quant_score_signals(conn, days=5, code=None, limit=0, refresh_existing=False):
    clauses = []
    if not refresh_existing:
        clauses.append("q.id IS NULL")
    params = []
    if days and days > 0:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S.%f")
        clauses.append("s.detected_at >= ?")
        params.append(since)
    if code:
        clauses.append("s.code = ?")
        params.append(code)
    limit_sql = ""
    if limit and limit > 0:
        limit_sql = "LIMIT ?"
        params.append(int(limit))
    where_sql = " AND ".join(clauses) if clauses else "1 = 1"

    rows = conn.execute("""
        SELECT
            s.id,
            s.detected_at,
            s.code,
            s.name,
            s.action_hint,
            s.confidence_score,
            s.risk_level,
            s.current_price,
            s.stop_loss,
            s.target_1,
            s.target_2,
            s.reason_json,
            s.summary_json,
            q.id AS quant_score_id
        FROM signal_logs s
        LEFT JOIN quant_signal_scores q
            ON q.signal_id = s.id
        WHERE {where}
        ORDER BY s.detected_at ASC, s.id ASC
        {limit_sql}
    """.format(where=where_sql, limit_sql=limit_sql), params).fetchall()
    return rows


def update_quant_signal_score(conn, quant_score_id, score):
    conn.execute("""
        UPDATE quant_signal_scores
        SET
            scored_at = ?,
            code = ?,
            action_hint = ?,
            quant_signal_score = ?,
            expected_value_score = ?,
            market_risk_score = ?,
            final_quant_score = ?,
            decision_side = ?,
            feature_json = ?,
            formula_version = ?
        WHERE id = ?
    """, (
        score.get("scored_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        score.get("code"),
        score.get("action_hint"),
        score.get("quant_signal_score"),
        score.get("expected_value_score"),
        score.get("market_risk_score"),
        score.get("final_quant_score"),
        score.get("decision_side"),
        json.dumps(score.get("feature_json") or {}, ensure_ascii=False),
        score.get("formula_version"),
        quant_score_id,
    ))
    conn.commit()
    return 1 if conn.total_changes is not None else 0


def _signal_from_row(row):
    reasons = _load_json(row["reason_json"])
    if not isinstance(reasons, list):
        reasons = []
    return {
        "code": row["code"],
        "name": row["name"],
        "action_hint": row["action_hint"],
        "confidence_score": row["confidence_score"],
        "risk_level": row["risk_level"],
        "current_price": row["current_price"],
        "stop_loss": row["stop_loss"],
        "target_1": row["target_1"],
        "target_2": row["target_2"],
        "reasons": reasons,
    }


def _load_json(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


if __name__ == "__main__":
    main()
