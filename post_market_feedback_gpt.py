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
            {
                "role": "system",
                "content": (
                    "너는 장마감 후 매매 신호 품질을 검토하는 분석 보조 AI다. "
                    "실시간 매수 지시가 아니라 다음 테스트를 위한 피드백만 작성한다."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=GPT_MAX_TOKENS,
    )
    finished_at = datetime.now()
    result = response.choices[0].message.content

    output_path = save_result(
        result=result,
        payload=payload,
        started_at=started_at,
        finished_at=finished_at,
        model=getattr(response, "model", GPT_MODEL),
        usage=extract_usage(response),
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
        "text_context": load_text_context(args.market_context),
    }


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

    return """
너는 장마감 후 주식 분석 시스템의 신호 품질을 검토하는 AI다.
아래 데이터는 장중 validation_signal의 사후 성과와, 장마감 후 반영할 수 있는 뉴스/공시/대중반응 컨텍스트다.

목표:
- 오늘 신호가 왜 맞았는지/틀렸는지 사후 피드백한다.
- 뉴스/공시/대중반응은 장중 실시간 공식에 크게 반영하지 않는다.
- 뉴스/공시/대중반응은 장마감 후 원인 분석과 다음날 리스크 메모를 만드는 데 사용한다.
- 다음 장중 테스트에 적용할 후보 공식과 가중치를 명확한 수식으로 제안한다.

규칙:
- 자동매매 지시가 아니라 다음 테스트용 피드백이다.
- 실시간 공식의 TextRiskScore 가중치는 1% 이하로 유지한다.
- 뉴스/커뮤니티 반응만으로 매수 관심도를 올리지 않는다.
- 공식은 MACD Line처럼 변수 정의가 분명해야 한다.
- 각 변수는 0~1 또는 0~100 스케일을 명시한다.
- 성과 표본이 작으면 강한 결론을 내리지 않는다.

데이터:
{data}

출력 형식:

# 장마감 피드백

## 1. 오늘 신호 성과 요약
- 전체 성과:
- 종목별 성과:
- 좋았던 신호:
- 나빴던 신호:

## 2. 뉴스/공시/대중반응 사후 해석
- 가격/거래량 설명에 도움이 된 뉴스:
- 과대해석하면 안 되는 뉴스:
- 공시/실적/가이던스 영향:
- 커뮤니티/댓글 반응의 한계:
- 다음날 리스크 메모:

## 3. 다음 테스트용 공식 제안
- 변수 정의:
- BreakoutScore 공식:
- TrendScore 공식:
- VolumeTradeScore 공식:
- FlowDerivScore 공식:
- TextRiskScore 공식, 가중치 1% 이하:
- RiskPenalty 공식:
- CostPenalty 공식:
- CombinedScore 공식:

## 4. 검증 계획
- 내일 유지할 규칙:
- 낮출 규칙:
- 올릴 규칙:
- 추가로 필요한 데이터:
""".format(data=data_json)


def save_result(result, payload, started_at, finished_at, model, usage):
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
