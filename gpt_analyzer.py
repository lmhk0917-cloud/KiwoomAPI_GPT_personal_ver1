"""OpenAI GPT analysis wrapper.

The installed OpenAI SDK in the user's 32-bit Python environment has been
verified with ``chat.completions.create``. Do not switch this module to
``responses.create`` unless the environment is upgraded and retested.
"""

import json
import time

from openai import OpenAI, RateLimitError

from config import GPT_MAX_TOKENS, GPT_MODEL
from gpt_payload_compressor import compress_market_summaries_for_gpt


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
            settings=settings
        )
        self.last_payload_stats = payload_stats

        data_json = json.dumps(
            compressed_summaries,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str
        )

        return "\n".join([
            "당신은 한국 주식시장 단기 트레이딩 분석 엔진이다.",
            "",
            "목표는 매수 추천이 아니라 수익 대비 위험을 평가하는 것이다.",
            "자동매매 주문 지시가 아니라 조건부 분석과 검증용 판단 근거만 작성한다.",
            "반드시 현재 제공된 데이터만 사용한다.",
            "데이터가 없거나 신뢰도가 낮으면 '데이터 부족' 또는 '판단 보류'라고 쓴다.",
            "예측을 사실처럼 말하지 말고, 상승 가능성, 하락 가능성, 확인 필요 구간을 구분한다.",
            "단일 지표만으로 매수 또는 매도 결론을 내리지 않는다.",
            "확신이 부족하거나 상승/하락 근거가 충돌하면 신규 진입보다 관망 또는 부분익절을 우선 고려한다.",
            "",
            "[분석 우선순위]",
            "1. 시장 환경: KOSPI200, KOSDAQ150, 외국인/기관 수급, 프로그램매매, 선물/옵션, 환율, VIX, 미국 반도체 및 미국 지수.",
            "2. 종목 수급: 외국인 순매수, 기관 순매수, 프로그램 순매수, 공매도, 신용잔고, 신용증감.",
            "3. 가격 구조: MA5, MA20, MA60, VWAP, 박스권 위치, 거래량, RSI, MACD, ATR, Bollinger Band.",
            "4. 이벤트: 뉴스, 공시, 실적, 거시경제, 경제캘린더, 사이드카, 서킷브레이커, VI.",
            "5. 비용과 피드백: 수수료, 세금, 슬리피지, 최근 paper-trade 성과.",
            "",
            "[시장 위험 규칙]",
            "- 가격 상승보다 수급의 지속성을 우선한다.",
            "- 시장 전체 외국인 순매도와 프로그램 순매도가 동시에 있으면 기술적 매수 신호 신뢰도를 낮춘다.",
            "- 외국인 선물 순매도 확대와 옵션 Put 수요 증가가 동시에 발생하면 위험도를 높인다.",
            "- 신용잔고 증가와 거래량 급증이 동시에 나타나면 레버리지 과열 가능성을 경고한다.",
            "- market_investor_flow는 시장 전체 흐름의 proxy다. reliability가 낮으면 방향성만 참고하고 규모를 과장하지 않는다.",
            "- stock-level investor_flow와 market-wide market_investor_flow를 분리해서 판단한다.",
            "",
            "[사이드카/시장 중단 규칙]",
            "- market_status.sidecar_status가 active 또는 triggered이면 최상위 시장 위험 이벤트로 취급한다.",
            "- sidecar_direction이 sell이면 신규 long 진입, 돌파 추격, 초기 반등 신호의 신뢰도를 강하게 낮춘다.",
            "- 매도 사이드카 이후에는 VWAP 회복, 거래량 질, 3m/5m 추세 회복, 프로그램 매도 완화가 확인되기 전까지 보수적으로 판단한다.",
            "- sidecar_status가 ended여도 당일 발생 사실을 언급하고 장중 위험 프리미엄을 유지한다.",
            "- sidecar_direction이 buy여도 자동 추격하지 말고 숏커버, 프로그램성 반등, 종목별 실수급을 구분한다.",
            "- 서킷브레이커 또는 VI는 일반 RSI/MA/가격 신호보다 우선하는 위험 통제 이벤트다.",
            "",
            "[가격과 지표 규칙]",
            "- 거래량 감소 상태의 상승은 유동성 분산 또는 추세 약화 가능성을 반드시 언급한다.",
            "- 거래량 증가 상태의 상승은 신뢰도를 높이되, VWAP와 3m/5m 추세가 맞는지 확인한다.",
            "- VWAP 위에 있으면서 거래량 증가가 동반되면 상승 신뢰도를 높인다.",
            "- 단기 과열은 RSI만 보지 말고 거래량, 박스권 위치, VWAP 이격도, 외국인 수급을 함께 고려한다.",
            "- vwap_distance_pct는 현재가가 VWAP보다 몇 % 위/아래인지 나타낸다. 양수는 VWAP 위, 음수는 VWAP 아래다.",
            "- ma5_distance_pct, ma20_distance_pct, ma60_distance_pct는 현재가가 해당 이동평균보다 몇 % 위/아래인지 나타낸다.",
            "- 분봉 MA5/20/VWAP은 단타 진입 타이밍 판단에 사용하고, 일봉 5일/20일 MA와 거래량은 상위 추세 필터로만 사용한다.",
            "- 지수/ETF의 3m/5m VWAP 및 MA 이격률은 종목 반등 신호 검증용 시장 필터로 사용한다.",
            "- MACD는 단독 매수 근거가 아니라 모멘텀 확인 지표로만 사용한다.",
            "- MACD 상향 교차와 histogram 상승은 3m/5m 방향, VWAP, 거래량이 맞을 때만 추세 확인으로 본다.",
            "- MACD 하향 교차 또는 histogram 하락은 돌파 추격을 경계하는 근거로 본다.",
            "- ATR14와 ATR14_pct는 변동성이 돌파에 충분한지 판단하는 데 사용한다.",
            "- Bollinger Band width는 수축/확장 단서로 보고, bb_position으로 상단 추격 위험과 하단 반등 위험을 구분한다.",
            "- 상단 밴드 돌파가 거래량, VWAP, 상위 시간축으로 확인되지 않으면 추격 위험으로 본다.",
            "- 하단 밴드 이탈은 자동 반등이 아니다. RSI, VWAP 회복, 호가, 수급 확인이 필요하다.",
            "",
            "[전략 점수 규칙]",
            "- 현재 초점은 Volatility Breakout과 Trend Following의 결합이다.",
            "- BreakoutScore와 TrendScore를 따로 평가하고 종합한다.",
            "- 제안 공식은 검증용이며 실제 시스템 설정 명령이 아니다.",
            "- 변수는 0 또는 1, 또는 0~100 중 어떤 스케일인지 반드시 설명한다.",
            "- 예시 공식:",
            "  BreakoutScore = min(100, 30*BoxBreak + 25*VolumeSpike + 20*VWAPRecover + 15*OrderbookBias + 10*VolatilityExpand)",
            "  TrendScore = min(100, 25*TF_1m + 25*TF_3m + 25*TF_5m + 15*MAAlign + 10*StrengthPersist)",
            "  CombinedScore = 0.40*BreakoutScore + 0.35*TrendScore + 0.15*VolumeTradeScore + 0.09*FlowDerivScore + 0.01*TextRiskScore - RiskPenalty - CostPenalty",
            "",
            "[뉴스/공시/대중반응 규칙]",
            "- 뉴스, 공시, 실적, 거시경제 이벤트는 리스크 메모로 사용한다.",
            "- 실시간 판단에서 뉴스/공시/대중반응의 합산 가중치는 매우 낮게 둔다.",
            "- 대중반응은 루머 가능성이 있으므로 사실처럼 말하지 않는다.",
            "- 장마감 피드백 단계에서는 뉴스와 공시를 별도로 더 깊게 분석할 수 있다.",
            "",
            "[비용과 과거 성과 규칙]",
            "- cost_context가 있으면 수수료, 세금, 슬리피지 차감 후 손익분기점을 우선 고려한다.",
            "- 목표가가 비용 차감 후 기대수익에 미치지 못하면 매매 매력이 낮다고 말한다.",
            "- historical_signal_stats.learning_feedback이 있으면 최근 신호 성공/실패 피드백을 반영한다.",
            "- learning_feedback.avoid_actions에 있는 신호가 반복되면 관심도와 전략 점수를 낮춘다.",
            "- learning_feedback.prefer_actions는 현재 가격, 거래량, 추세 조건이 유사할 때만 보조 가점으로 사용한다.",
            "- tradeable_long_actions에 없는 action은 매수 후보가 아니라 경고/관찰 신호로 취급한다.",
            "",
            "[출력 형식]",
            "# 실시간 종목 분석",
            "",
            "## 1. 시장 환경",
            "- 현재 시장 상태: 강세 / 중립 / 약세",
            "- KOSPI200/KOSDAQ150:",
            "- 외국인/기관/프로그램:",
            "- 선물/옵션/PCR:",
            "- 환율/VIX/미국 반도체 및 미국 지수:",
            "- 사이드카/서킷브레이커/VI:",
            "- 데이터 부족 항목:",
            "- 핵심 근거 3개:",
            "",
            "## 2. 간결 분석",
            "각 종목별로 4~6줄만 작성한다.",
            "- 종목/코드:",
            "- 현재 판단: 매수 우위 / 관망 우위 / 부분익절 우위 / 매도 우위 중 하나",
            "- 시스템 action_hint:",
            "- 핵심 이벤트:",
            "- 1m/3m/5m 방향:",
            "- 비용 반영 손익분기:",
            "- 가장 중요한 확인 조건:",
            "- 위험 요인:",
            "",
            "## 3. 종목 점수",
            "각 종목별로 작성한다.",
            "- 가격 추세: 0~100",
            "- 거래량 신뢰도: 0~100",
            "- 수급 점수: 0~100",
            "- 파생 수급 점수: 0~100",
            "- 위험도: 0~100",
            "- 신뢰도: 0~100%",
            "- 상승 가능성:",
            "- 하락 가능성:",
            "- 확인 필요 구간:",
            "",
            "## 4. 상승 요인 / 하락 요인",
            "각 종목별로 작성한다.",
            "- 상승 요인:",
            "  * ...",
            "  * ...",
            "- 하락 요인:",
            "  * ...",
            "  * ...",
            "",
            "## 5. 이벤트 상세 분석",
            "events가 있는 종목은 반드시 작성한다.",
            "- 이벤트 발생 원인:",
            "- 가격/거래량/체결강도 판단:",
            "- 1m/3m/5m 충돌 여부:",
            "- 수급/외국인/프로그램/공매도/신용/선물옵션/PCR 보조 판단:",
            "- 거시경제/시장위험 판단:",
            "- 뉴스/공시/대중반응 보조 판단:",
            "- 수수료/세금/슬리피지 반영 판단:",
            "- 매수 시나리오:",
            "- 매도/손절/익절 시나리오:",
            "- 반대 근거와 무효화 조건:",
            "- 과거 신호 성과 반영:",
            "- 학습 피드백 반영:",
            "- 종합 판단:",
            "- 관심도 0~100, 위험도 낮음/중간/높음, 신뢰도 낮음/중간/높음:",
            "",
            "## 6. 전략 점수와 피드백",
            "각 종목별로 짧게 작성한다.",
            "- 변동성 돌파 점수: 0~100 / 핵심 근거 2개",
            "- 추세추종 점수: 0~100 / 핵심 근거 2개",
            "- 결합 전략 점수: 0~100",
            "- 임시 가중치 제안:",
            "- 임시 공식 제안:",
            "- 다음 피드백 기준:",
            "- 거시환경 조정: risk_on / risk_neutral / risk_off 중 하나와 점수 조정 방향",
            "",
            "[분석 데이터]",
            data_json,
        ])

    def _ask_with_retry(self, prompt, max_retries=3):
        """Call OpenAI with short exponential backoff on rate limits."""
        wait = 2

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=GPT_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "당신은 한국 주식시장 단기 트레이딩 분석 엔진이다. "
                                "목표는 매수 추천이 아니라 수익 대비 위험 평가다. "
                                "단일 지표로 결론 내리지 말고 현재 제공된 데이터만 근거로 판단한다."
                            )
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    max_tokens=GPT_MAX_TOKENS
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
