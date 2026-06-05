"""Simple random-tick GPT smoke test.

Use ``simulate_debug.py`` for the full event/database path. This file remains
as a compact test for indicator creation and a direct GPT call.
"""

import os
import random
from datetime import datetime, timedelta

from data_store import TickStore
from env_loader import load_project_env
from indicators import make_ohlcv_from_ticks, add_indicators, summarize_for_gpt
from gpt_analyzer import GPTAnalyzer


load_project_env()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def make_mock_ticks(code="005930", start_price=74200, count=300):
    """Generate random Kiwoom-like ticks for quick local testing."""
    ticks = []
    now = datetime.now() - timedelta(minutes=40)
    price = start_price

    for i in range(count):
        price += random.randint(-80, 100)

        tick = {
            "code": code,
            "trade_time": now.strftime("%H%M%S"),
            "price": price,
            "change_rate": 0.0,
            "acc_volume": 1000000 + i * random.randint(50, 300),
            "tick_volume": random.randint(10, 500),
            "open_price": start_price,
            "high_price": price + random.randint(0, 100),
            "low_price": price - random.randint(0, 100),
            "strength": random.uniform(80, 130),
            "received_at": now.strftime("%Y-%m-%d %H:%M:%S.%f")
        }

        ticks.append(tick)
        now += timedelta(seconds=8)

    return ticks


if __name__ == "__main__":
    tick_store = TickStore()

    mock_ticks = make_mock_ticks(
        code="005930",
        start_price=74200,
        count=300
    )

    for tick in mock_ticks:
        tick_store.add_tick(tick)

    ticks = tick_store.get_recent_ticks("005930")

    ohlcv = make_ohlcv_from_ticks(ticks, interval="1min")
    indicator_df = add_indicators(ohlcv)

    summary = summarize_for_gpt(
        code="005930",
        name="삼성전자",
        indicator_df=indicator_df
    )

    print("==== GPT 전달 요약 데이터 ====")
    print(summary)

    if summary is None:
        print("summary 생성 실패")
    else:
        gpt = GPTAnalyzer(api_key=OPENAI_API_KEY)
        result = gpt.analyze([summary])

        print("\n==== GPT 분석 결과 ====")
        print(result)
