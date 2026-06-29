"""Post-market GPT feedback using paper-trade results and text context.

Realtime GPT calls keep news/public reaction weight very low. This script is
for after the close: import or crawl news/disclosure/reaction context first,
then ask GPT to review whether the intraday rules and formula weights should be
adjusted for later backtests.
"""

import argparse
import json
import os
from datetime import datetime

from openai import OpenAI

from app_paths import DEFAULT_DB_PATH, EXPORTS_DIR, ensure_app_dirs, setup_runtime_logging
from config import GPT_MODEL, GPT_MAX_TOKENS, MARKET_CONTEXT_PATH
from data_store import TickStore
from env_loader import load_project_env
from paper_trade_report import build_report
from shared_context_auto_export import export_shared_context


SYSTEM_PROMPT = (
    "너는 장마감 후 paper-trade 결과와 시장 컨텍스트를 검토하는 분석 보조 AI다. "
    "실시간 매수 지시를 하지 말고, 다음 테스트를 위한 위험/수익 피드백만 작성한다."
)


def numeric_conventions():
    return {
        "return_pct_fields_are_percent_points": True,
        "do_not_rescale_pct_values": True,
        "report_pct_values_verbatim": True,
        "rounding": "Keep *_pct return values as given, or round to 3 decimals. Never multiply by 100.",
        "examples": {
            "0.185": "0.185%, not 18.5%",
            "0.924": "0.924%, not 92.4%",
            "-0.125": "-0.125%, not -12.5%",
        },
        "interpretation": {
            "avg_return_60m_pct": "Already a percent return over 60 minutes.",
            "avg_net_return_60m_pct": "Already a percent return after estimated round-trip cost.",
            "win_rate_60m_pct": "Already a percent rate on a 0 to 100 scale.",
        },
    }


def main():
    args = parse_args()
    setup_runtime_logging("post_market_feedback_gpt")
    load_project_env()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not configured in .env")

    store = TickStore(db_path=args.db)
    try:
        payload = build_feedback_payload(store.conn, args)
    finally:
        store.close()

    prompt = build_prompt(payload)
    client = OpenAI(api_key=api_key)
    started_at = datetime.now()
    response = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=GPT_MAX_TOKENS,
    )
    finished_at = datetime.now()
    result = response.choices[0].message.content
    unit_warnings = validate_result_units(result, payload)

    output_path = save_result(
        result=result,
        payload=payload,
        started_at=started_at,
        finished_at=finished_at,
        model=getattr(response, "model", GPT_MODEL),
        usage=extract_usage(response),
        unit_warnings=unit_warnings,
    )

    print("========== Post-Market Feedback GPT ==========")
    print("status: success")
    print("model:", getattr(response, "model", GPT_MODEL))
    print("output_path:", output_path)
    print("prompt_chars:", len(prompt))
    print("duration_ms:", int((finished_at - started_at).total_seconds() * 1000))
    usage = extract_usage(response)
    print("prompt_tokens:", usage.get("prompt_tokens"))
    print("completion_tokens:", usage.get("completion_tokens"))
    print("total_tokens:", usage.get("total_tokens"))
    if unit_warnings:
        print("unit_warnings:")
        for warning in unit_warnings:
            print(" -", warning)
    export_shared_context(reason="post_market_feedback_gpt")
    print()
    print(result)


def parse_args():
    parser = argparse.ArgumentParser(description="Run post-market GPT feedback analysis.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--days", type=int, default=1, help="Paper-trade lookback window in days")
    parser.add_argument("--min-sample", type=int, default=5, help="Minimum evaluated rows for trusted labels")
    parser.add_argument("--recent-limit", type=int, default=20, help="Recent evaluated signals to include")
    parser.add_argument("--code", help="Optional stock code filter")
    parser.add_argument(
        "--market-context",
        default=MARKET_CONTEXT_PATH,
        help="market_context.json or imported/crawled context JSON",
    )
    return parser.parse_args()


def build_feedback_payload(conn, args):
    paper_report = build_report(
        conn=conn,
        code=args.code,
        days=args.days,
        min_sample=args.min_sample,
        recent_limit=args.recent_limit,
    )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "mode": "post_market_feedback",
        "scope": {
            "code": args.code,
            "days": args.days,
            "min_sample": args.min_sample,
        },
        "paper_trade_report": paper_report,
        "authoritative_metrics": build_authoritative_metrics(paper_report),
        "text_context": load_text_context(args.market_context),
        "numeric_conventions": numeric_conventions(),
    }


def build_authoritative_metrics(paper_report):
    overview = paper_report.get("overview", {})
    sample = paper_report.get("sample_summary", {})
    return {
        "source": "paper_trade_report",
        "usage_rule": "Use these values as the authoritative numbers in prose. *_pct values are already percentages.",
        "overview": select_metric_fields(overview, [
            "signal_count",
            "evaluated_count",
            "evaluated_60m_count",
            "partial_evaluated_count",
            "pending_count",
            "avg_return_30m_pct",
            "avg_return_60m_pct",
            "avg_net_return_30m_pct",
            "avg_net_return_60m_pct",
            "win_rate_60m_pct",
            "net_win_rate_60m_pct",
            "directional_success_60m_pct",
            "stop_loss_hit_rate_pct",
        ]),
        "sample_summary": sample,
        "by_action": authoritative_group_rows(paper_report.get("by_action", [])),
        "by_decision_side": authoritative_group_rows(paper_report.get("by_decision_side", [])),
        "by_code": authoritative_group_rows(paper_report.get("by_code", [])),
        "by_code_action": authoritative_group_rows(paper_report.get("by_code_action", [])),
    }


def authoritative_group_rows(rows):
    fields = [
        "group_name",
        "signal_count",
        "evaluated_count",
        "evaluated_60m_count",
        "partial_evaluated_count",
        "pending_count",
        "avg_return_60m_pct",
        "avg_net_return_60m_pct",
        "win_rate_60m_pct",
        "net_win_rate_60m_pct",
        "directional_success_60m_pct",
        "stop_loss_hit_rate_pct",
        "sample_label",
        "profit_label",
        "directional_label",
        "interpretation_hint",
    ]
    return [select_metric_fields(row, fields) for row in rows]


def select_metric_fields(row, fields):
    return {field: row.get(field) for field in fields if field in row}


def load_text_context(path):
    if not path:
        return {}

    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)

    if not os.path.exists(path):
        return {
            "source": path,
            "loaded": False,
            "reason": "context file not found",
        }

    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    return {
        "source": path,
        "loaded": True,
        "data": data,
    }


def build_prompt(payload):
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    unit_guard = """
CRITICAL NUMERIC UNIT RULES:
- Fields ending in _pct are already percent values.
- Return fields such as avg_return_60m_pct and avg_net_return_60m_pct are percent points, not decimal fractions.
- Example: 0.185 means 0.185%, not 18.5%.
- Example: 0.924 means 0.924%, not 92.4%.
- Example: -0.125 means -0.125%, not -12.5%.
- Never multiply *_pct values by 100.
- If summarizing returns, copy values from avg_return_*_pct and avg_net_return_*_pct as-is with a % suffix.
- Do not call a result profitable when avg_net_return_60m_pct is negative.
- Prefer authoritative_metrics for every quoted number.
- Keep profit_label and directional_label separate.
- Keep partial_evaluated_count and pending_count separate from 60m headline returns.
"""

    return unit_guard + """
너는 장마감 후 주식 분석 시스템의 validation signal을 검토하는 AI다.
아래 데이터는 저장된 paper-trade 결과, quant score, GPT 판단, 시장 컨텍스트다.

목표:
- 오늘 신호가 사후 수익률 기준으로 맞았는지 평가한다.
- GPT 판단과 정량식이 어디에서 일치/불일치했는지 설명한다.
- 다음 테스트에 반영할 수 있는 수식 개선과 검증 계획을 제안한다.
- 자동매매 지시, 매수/매도 명령, 포지션 크기 제안은 하지 않는다.

규칙:
- GPT는 위험/수익 평가자이며 매수 지시자가 아니다.
- 뉴스/커뮤니티/텍스트 컨텍스트만으로 매수 관점을 높이지 않는다.
- TextRiskScore 또는 GPTAgreementScore의 실시간 비중은 낮게 유지한다.
- 표본이 부족하면 강한 결론을 내리지 않는다.
- 각 변수는 0~1 또는 0~100 스케일을 명확히 표시한다.
- 서킷브레이커, 시장 급락, VI, 사이드카는 hard risk override로 우선 처리한다.

데이터:
{data}

출력 형식:

# 장마감 피드백
## 1. 오늘 신호 성과 요약
- 전체 성과:
- 종목별 성과:
- 잘 맞은 신호:
- 나빴던 신호:

## 2. GPT와 정량식 비교
- 일치한 판단:
- 불일치한 판단:
- GPT가 과대평가한 요소:
- 정량식이 놓친 요소:

## 3. 시장 컨텍스트 사후 해석
- 가격/거래량으로 설명 가능한 부분:
- 뉴스/공시/매크로로 보완되는 부분:
- 서킷브레이커/급락/VI/사이드카 반영 여부:
- 다음날 리스크 메모:

## 4. 다음 테스트용 수식 제안
- TrendScore:
- BreakoutScore:
- VolumeFlowScore:
- ExpectedValueScore:
- MarketRegimeScore:
- RiskRewardScore:
- GPTAgreementScore:
- RiskPenalty:
- CostPenalty:
- CombinedScore:

## 5. 검증 계획
- 내일 유지할 규칙:
- 줄일 규칙:
- 버릴 규칙:
- 추가로 필요한 데이터:
""".format(data=data_json)


def collect_return_pct_values(value, path="payload"):
    values = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = "{}.{}".format(path, key)
            if (
                key.endswith("_pct")
                and ("return" in key or "max_gain" in key or "max_loss" in key)
                and isinstance(child, (int, float))
            ):
                values.append((child_path, float(child)))
            else:
                values.extend(collect_return_pct_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(collect_return_pct_values(child, "{}[{}]".format(path, index)))
    return values


def validate_result_units(result, payload):
    if not result:
        return []

    warnings = []
    result_text = str(result)
    seen = set()
    for path, value in collect_return_pct_values(payload.get("paper_trade_report", {}), "paper_trade_report"):
        if abs(value) < 0.001 or abs(value) >= 10:
            continue
        scaled = value * 100
        for decimals in (1, 2, 3):
            scaled_text = "{:.{}f}".format(scaled, decimals).rstrip("0").rstrip(".")
            needle = "{}%".format(scaled_text)
            if needle in result_text and (path, needle) not in seen:
                warnings.append(
                    "possible pct rescale: {}={} may have been reported as {}".format(path, value, needle)
                )
                seen.add((path, needle))
    return warnings


def save_result(result, payload, started_at, finished_at, model, usage, unit_warnings=None):
    ensure_app_dirs()
    stamp = finished_at.strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(EXPORTS_DIR, "post_market_feedback_{}.md".format(stamp))

    with open(output_path, "w", encoding="utf-8") as fp:
        fp.write("# Post-Market GPT Feedback\n\n")
        fp.write("- started_at: {}\n".format(started_at.strftime("%Y-%m-%d %H:%M:%S.%f")))
        fp.write("- finished_at: {}\n".format(finished_at.strftime("%Y-%m-%d %H:%M:%S.%f")))
        fp.write("- model: {}\n".format(model))
        fp.write("- prompt_tokens: {}\n".format(usage.get("prompt_tokens")))
        fp.write("- completion_tokens: {}\n".format(usage.get("completion_tokens")))
        fp.write("- total_tokens: {}\n\n".format(usage.get("total_tokens")))
        if unit_warnings:
            fp.write("## Unit Warnings\n\n")
            for warning in unit_warnings:
                fp.write("- {}\n".format(warning))
            fp.write("\n")
        fp.write(result or "")
        fp.write("\n\n## Payload Snapshot\n\n")
        fp.write("```json\n")
        fp.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        fp.write("\n```\n")

    return output_path


def extract_usage(response):
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


if __name__ == "__main__":
    main()
