"""Minimal live OpenAI API smoke test.

This intentionally uses the same GPTAnalyzer/chat.completions path as the
realtime app, but sends a tiny synthetic payload so cost and latency stay low.
It does not write analysis_results or gpt_call_logs.
"""

import argparse
import os
from datetime import datetime

from env_loader import load_project_env
from gpt_analyzer import GPTAnalyzer


def main():
    args = parse_args()
    load_project_env()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("GPT_SMOKE_RESULT=FAIL reason=OPENAI_API_KEY_missing")

    summary = build_smoke_summary()
    gpt = GPTAnalyzer(api_key=api_key)

    started_at = datetime.now()
    result = gpt.analyze([summary], settings={"GPT_INPUT_MAX_TEXT_CHARS": 300})
    finished_at = datetime.now()

    status = "failed" if gpt.last_error_message else "success"
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    print("GPT_SMOKE_RESULT={}".format("PASS" if status == "success" else "FAIL"))
    print("status={}".format(status))
    print("model={}".format(gpt.last_model))
    print("duration_ms={}".format(duration_ms))
    print("prompt_chars={}".format(gpt.last_prompt_chars))
    print("prompt_tokens={}".format(gpt.last_usage.get("prompt_tokens")))
    print("completion_tokens={}".format(gpt.last_usage.get("completion_tokens")))
    print("total_tokens={}".format(gpt.last_usage.get("total_tokens")))

    if gpt.last_error_message:
        print("error_message={}".format(gpt.last_error_message))
        raise SystemExit(1)

    preview = (result or "").replace("\r", " ").replace("\n", " ")[:args.preview_chars]
    print("response_preview={}".format(preview))


def parse_args():
    parser = argparse.ArgumentParser(description="Run a tiny live GPT API smoke test.")
    parser.add_argument("--preview-chars", type=int, default=180)
    return parser.parse_args()


def build_smoke_summary():
    return {
        "code": "005930",
        "name": "삼성전자",
        "market_snapshot": {
            "current_price": 100.0,
            "change_rate": 0.0,
            "received_at": "smoke_test",
        },
        "events": [
            {
                "type": "SMOKE_TEST",
                "timeframe": "test",
                "message": "Connectivity and prompt-path test only.",
                "value": None,
            }
        ],
        "validation_signal": {
            "action_hint": "OBSERVE_EVENT",
            "confidence_score": 50,
            "risk_level": "medium",
            "current_price": 100.0,
            "reasons": ["Smoke test payload. Do not infer market direction."],
        },
        "timeframes": {
            "1m": {
                "latest": {"close": 100.0, "return_1bar_pct": 0.0},
                "moving_average": {"ma5": 100.0, "ma20": 100.0, "price_above_ma5": False},
                "momentum": {"rsi14": 50.0},
                "volume": {"volume_ratio_5": 1.0, "volume_ratio_20": 1.0},
                "vwap": {"vwap": 100.0, "vwap_distance_pct": 0.0, "price_above_vwap": False},
                "trend": {"consecutive_up_bars": 0, "consecutive_down_bars": 0},
                "box_range": {"box_high": 101.0, "box_low": 99.0, "current_position_in_box": 0.5},
            }
        },
        "market_context": {
            "market_status": {
                "sidecar_status": "inactive",
                "circuit_breaker_status": "inactive",
                "vi_status": "inactive",
                "summary": "Smoke test context.",
            },
            "market_indices": {
                "kospi200_change_pct": 0.0,
                "kosdaq_change_pct": 0.0,
            },
            "market_investor_flow": {
                "combined_foreign_net_value": None,
                "combined_institution_net_value": None,
                "reliability": "smoke_test",
            },
            "market_program_trading": {
                "total_net_value": None,
            },
            "macro_context": {
                "risk_regime": "risk_neutral",
                "reliability": "smoke_test",
            },
        },
        "historical_signal_stats": {
            "sample_size": 0,
            "evaluated_count": 0,
            "note": "Smoke test only.",
        },
    }


if __name__ == "__main__":
    main()
