"""Import manual external market context into SQLite.

This is a staging tool for news, disclosures, and public-reaction data.
It stores the raw context first so GPT input compression can be added later
without losing source evidence.
"""

import argparse
import copy
import json
import os
from datetime import datetime

from app_paths import DEFAULT_DB_PATH, PROJECT_DIR
from config import MARKET_CONTEXT_PATH
from data_store import TickStore


DEFAULT_CONTEXT_PATH = os.path.join(PROJECT_DIR, MARKET_CONTEXT_PATH)

DEFAULT_SECTIONS = {
    "market_indices",
    "market_status",
    "sector_context",
    "reference_levels",
    "derivatives",
    "short_selling",
    "credit",
    "investor_flow",
    "orderbook",
    "program_trading",
    "market_program_trading",
    "news",
    "disclosures",
    "public_reaction",
}


def main():
    parser = argparse.ArgumentParser(description="Import external context snapshots into SQLite.")
    parser.add_argument("--file", required=True, help="JSON file to import")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--sections", help="Comma-separated section whitelist")
    parser.add_argument(
        "--merge-market-context-json",
        action="store_true",
        help="Also merge the input JSON into market_context.json for current GPT runtime context"
    )
    parser.add_argument(
        "--market-context-path",
        default=DEFAULT_CONTEXT_PATH,
        help="Target market_context.json path when --merge-market-context-json is used"
    )
    args = parser.parse_args()

    data = load_json(args.file)
    sections = parse_sections(args.sections)

    store = TickStore(db_path=args.db)
    try:
        saved_count = import_snapshots(store, data, sections)
    finally:
        store.close()

    if args.merge_market_context_json:
        merge_market_context_json(args.market_context_path, data)

    print("saved_market_context_snapshots={}".format(saved_count))
    if args.merge_market_context_json:
        print("merged_market_context_json={}".format(args.market_context_path))


def load_json(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def parse_sections(raw_value):
    if not raw_value:
        return DEFAULT_SECTIONS

    return set(
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    )


def import_snapshots(store, data, sections):
    saved_count = 0

    for scope, code, section, payload in iter_snapshot_payloads(data, sections):
        store.save_market_context_snapshot(
            scope=scope,
            code=code,
            section=section,
            payload=payload,
            collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        )
        saved_count += 1

    return saved_count


def iter_snapshot_payloads(data, sections):
    global_context = data.get("global") or {}
    global_asof = global_context.get("asof") or data.get("asof")

    for section, payload in global_context.items():
        if section == "asof" or section not in sections:
            continue
        yield "global", None, section, normalize_payload(payload, global_asof)

    for code, code_context in (data.get("codes") or {}).items():
        code_asof = code_context.get("asof") or global_asof
        for section, payload in code_context.items():
            if section == "asof" or section not in sections:
                continue
            yield "code", code, section, normalize_payload(payload, code_asof)


def normalize_payload(payload, fallback_asof):
    if isinstance(payload, dict):
        normalized = copy.deepcopy(payload)
    else:
        normalized = {"value": payload}

    if fallback_asof and not normalized.get("asof"):
        normalized["asof"] = fallback_asof

    if not normalized.get("source"):
        normalized["source"] = "manual_external_context"

    return normalized


def merge_market_context_json(path, incoming):
    existing = {}
    if os.path.exists(path):
        existing = load_json(path)

    merged = copy.deepcopy(existing)
    deep_update(merged, incoming)

    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    with open(path, "w", encoding="utf-8") as fp:
        json.dump(merged, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def deep_update(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


if __name__ == "__main__":
    main()
