"""Run lightweight SQLite planner maintenance without deleting data."""

import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app_paths import DEFAULT_DB_PATH


def main():
    parser = argparse.ArgumentParser(description="Run PRAGMA optimize on the SQLite DB.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Run ANALYZE before PRAGMA optimize. Use after market close.",
    )
    args = parser.parse_args()
    result = optimize_db(args.db, analyze=args.analyze)
    print("DB_OPTIMIZE_STATUS=ok")
    for key in sorted(result):
        print("{}={}".format(key, result[key]))


def optimize_db(db_path, analyze=False):
    if not os.path.exists(db_path):
        raise RuntimeError("DB not found: {}".format(db_path))

    conn = sqlite3.connect(db_path)
    try:
        if analyze:
            conn.execute("ANALYZE")
        optimize_rows = conn.execute("PRAGMA optimize").fetchall()
        conn.commit()
        return {
            "db_path": db_path,
            "db_size_mb": round(os.path.getsize(db_path) / 1024.0 / 1024.0, 3),
            "analyze": bool(analyze),
            "pragma_optimize_rows": len(optimize_rows),
        }
    finally:
        conn.close()


if __name__ == "__main__":
    main()
