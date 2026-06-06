"""OpenAI GPT analysis wrapper.

The installed OpenAI SDK in the user's 32-bit Python environment has been
verified with ``chat.completions.create``. Do not switch this module to
``responses.create`` unless the environment is upgraded and retested.
"""

import json
import os
import time

from openai import OpenAI, RateLimitError

from app_paths import PROJECT_DIR
from config import GPT_MAX_TOKENS, GPT_MODEL
from gpt_payload_compressor import compress_market_summaries_for_gpt


PROMPT_DIR = os.path.join(PROJECT_DIR, "prompts")
SYSTEM_PROMPT_PATH = os.path.join(PROMPT_DIR, "trading_analysis_system_ko.txt")
USER_PROMPT_PATH = os.path.join(PROMPT_DIR, "trading_analysis_user_ko.txt")

DEFAULT_SYSTEM_PROMPT = (
    "당신은 한국 주식시장 단기 트레이딩 분석 엔진이다. "
    "목표는 매수 추천이 아니라 수익 대비 위험 평가다. "
    "단일 지표로 결론을 내리지 말고 현재 제공된 데이터만 근거로 판단한다."
)

DEFAULT_USER_PROMPT = """당신은 한국 주식시장 단기 트레이딩 분석 엔진이다.

목표는 매수 추천이 아니라 수익 대비 위험을 평가하는 것이다.
자동매매 주문 지시가 아니라 조건부 분석과 검증용 판단 근거만 작성한다.
반드시 현재 제공된 데이터만 사용한다.
데이터가 없거나 신뢰도가 낮으면 데이터 부족 또는 판단 보류라고 말한다.
예측을 사실처럼 말하지 말고 상승 가능성, 하락 가능성, 확인 필요 구간을 구분한다.
확신이 부족하면 신규 진입보다 관망을 우선한다.

[분석 데이터]
{data_json}
"""


def _read_prompt_file(path, fallback):
    """Load a UTF-8 prompt file and fall back to a compact built-in prompt."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except OSError:
        return fallback.strip()

    return content or fallback.strip()


class GPTAnalyzer:
    """Build the Korean market-analysis prompt and call OpenAI."""

    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key)
        self.last_error_message = None
        self.last_model = GPT_MODEL
        self.last_usage = {}
        self.last_prompt_chars = 0
        self.last_response_chars = 0
        self.last_payload_stats = {}

    def analyze(self, market_summaries, settings=None):
        """Analyze one batch of event-triggered symbol summaries."""
        self.last_error_message = None
        self.last_model = GPT_MODEL
        self.last_usage = {}
        self.last_prompt_chars = 0
        self.last_response_chars = 0
        self.last_payload_stats = {}

        prompt = self._build_prompt(market_summaries, settings=settings)
        self.last_prompt_chars = len(prompt)
        return self._ask_with_retry(prompt)

    def _build_prompt(self, market_summaries, settings=None):
        """Create a compact prompt so output is comparable across runs."""
        compressed_summaries, payload_stats = compress_market_summaries_for_gpt(
            market_summaries=market_summaries,
            settings=settings,
        )
        self.last_payload_stats = payload_stats

        data_json = json.dumps(
            compressed_summaries,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

        template = _read_prompt_file(USER_PROMPT_PATH, DEFAULT_USER_PROMPT)
        if "{data_json}" in template:
            return template.replace("{data_json}", data_json)
        return "{}\n\n[분석 데이터]\n{}".format(template, data_json)

    def _ask_with_retry(self, prompt, max_retries=3):
        """Call OpenAI with short exponential backoff on rate limits."""
        wait = 2
        system_prompt = _read_prompt_file(SYSTEM_PROMPT_PATH, DEFAULT_SYSTEM_PROMPT)

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=GPT_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    max_tokens=GPT_MAX_TOKENS,
                )

                result = response.choices[0].message.content
                self.last_model = getattr(response, "model", GPT_MODEL)
                self.last_usage = self._extract_usage(response)
                self.last_response_chars = len(result or "")
                return result

            except RateLimitError:
                self.last_error_message = "OpenAI rate limit"
                print("Rate limit. retry after {} seconds.".format(wait))
                time.sleep(wait)
                wait *= 2

            except Exception as exc:
                self.last_error_message = str(exc)
                return "GPT call error: {}".format(exc)

        self.last_error_message = "OpenAI rate limit retries exceeded"
        return "GPT analysis failed because rate limit retries were exceeded"

    def _extract_usage(self, response):
        """Return token usage from the OpenAI SDK response when available."""
        usage = getattr(response, "usage", None)

        if not usage:
            return {}

        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
