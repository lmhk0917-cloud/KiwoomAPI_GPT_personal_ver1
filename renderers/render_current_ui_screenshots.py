"""Render the current PyQt dashboard with example data.

This creates a throwaway SQLite DB with realistic rows, opens the real
``Dashboard`` widget, and saves screenshots for quick visual review.
"""

import os
import sys
from datetime import datetime, timedelta

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from data_store import TickStore
from settings_store import SettingsStore
from ui_dashboard import Dashboard
from app_paths import DATA_DIR, SCREENSHOT_DIR, ensure_app_dirs


DB_PATH = os.path.join(DATA_DIR, "ui_current_example.db")
SCREENSHOTS = {
    "overview": os.path.join(SCREENSHOT_DIR, "ui_current_overview.png"),
    "chart": os.path.join(SCREENSHOT_DIR, "ui_current_chart.png"),
    "operations": os.path.join(SCREENSHOT_DIR, "ui_current_operations.png"),
    "market_context": os.path.join(SCREENSHOT_DIR, "ui_current_market_context.png"),
    "watchlist": os.path.join(SCREENSHOT_DIR, "ui_current_watchlist.png"),
}


WATCH_CODES = {
    "005930": "Samsung Electronics",
    "000660": "SK hynix",
    "035720": "Kakao",
    "035420": "NAVER",
}


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", default_qt_platform())
    build_example_db()

    app = QApplication(sys.argv)
    dashboard = Dashboard(db_path=DB_PATH)
    dashboard.resize(1500, 900)
    dashboard.show()
    app.processEvents()

    capture_tab(dashboard, "개요", SCREENSHOTS["overview"])
    capture_tab(dashboard, "차트", SCREENSHOTS["chart"])
    capture_tab(dashboard, "운영", SCREENSHOTS["operations"])
    capture_tab(dashboard, "시장 컨텍스트", SCREENSHOTS["market_context"])
    capture_tab(dashboard, "관심종목", SCREENSHOTS["watchlist"])

    dashboard.close()

    print("DB={}".format(DB_PATH))
    for label, path in SCREENSHOTS.items():
        print("{}={}".format(label, path))


def default_qt_platform():
    """Prefer visible text rendering on Windows; use offscreen elsewhere."""
    if sys.platform.startswith("win"):
        return "windows"
    return "offscreen"


def build_example_db():
    ensure_app_dirs()

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    store = TickStore(db_path=DB_PATH)
    settings_store = SettingsStore(conn=store.conn)
    settings_store.update_setting("WATCH_CODES", WATCH_CODES)
    settings_store.update_setting("NOTIFICATION_CHANNELS", ["console", "telegram"])
    settings_store.update_setting("MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH", "24")

    base_time = datetime(2026, 5, 22, 9, 34, 0)
    scenarios = [
        ("005930", "Samsung Electronics", 298500, 61.4, "AVOID_CHASE", "high"),
        ("000660", "SK hynix", 386500, 47.8, "WATCH_PULLBACK", "medium"),
        ("035720", "Kakao", 64200, 32.1, "WATCH_REBOUND", "medium"),
        ("035420", "NAVER", 231500, 55.6, "OBSERVE_EVENT", "low"),
    ]

    for index, scenario in enumerate(scenarios):
        code, name, price, rsi, action, risk = scenario
        now = base_time + timedelta(minutes=index)
        add_ticks(store, code, price, now)
        summary = make_summary(code, name, price, rsi, now, action, risk)
        store.save_analysis_result(summary, make_gpt_text(name, code, price), analyzed_at=fmt(now))
        store.save_event_logs(summary, summary["events"], detected_at=fmt(now), gpt_requested=True)
        signal_id = store.save_signal_log(summary["validation_signal"], summary, detected_at=fmt(now))
        store.save_paper_trade_result(make_paper_result(signal_id, code, price, now))
        store.save_notification_logs(
            summary=summary,
            events=summary["events"],
            results=[
                {"channel": "console", "status": "success"},
                {"channel": "telegram", "status": "success"},
            ],
            message="[example] {} event notification".format(name),
            sent_at=fmt(now)
        )

    add_gpt_logs(store, base_time)
    add_historical_bars(store, base_time)
    add_context_snapshots(store, base_time)
    store.close()


def add_ticks(store, code, price, now):
    for idx in range(40):
        tick_time = now - timedelta(seconds=(40 - idx) * 3)
        store.add_tick({
            "code": code,
            "trade_time": tick_time.strftime("%H%M%S"),
            "price": int(price + ((idx % 5) - 2) * 100),
            "change_rate": round(((idx % 9) - 4) * 0.08, 3),
            "acc_volume": 1200000 + idx * 2500,
            "tick_volume": 500 + idx * 20,
            "open_price": int(price * 0.992),
            "high_price": int(price * 1.018),
            "low_price": int(price * 0.981),
            "strength": 118.5 + idx * 0.6,
            "received_at": fmt(tick_time),
        })


def make_summary(code, name, price, rsi, now, action, risk):
    target_1 = round(price * 1.012, 2)
    target_2 = round(price * 1.026, 2)
    stop_loss = round(price * 0.985, 2)

    one_minute = {
        "bar_count": 52,
        "latest": {
            "time": fmt(now),
            "open": price - 700,
            "high": price + 900,
            "low": price - 1100,
            "close": price,
            "volume": 18200,
            "return_1bar_pct": 0.42,
        },
        "moving_average": {
            "ma5": price - 250,
            "ma20": price + 180,
            "ma60": price - 1250,
            "price_above_ma5": True,
            "price_above_ma20": False,
            "price_above_ma60": True,
        },
        "momentum": {"rsi14": rsi},
        "volume": {
            "volume_ma5": 9900,
            "volume_ma20": 8200,
            "volume_ratio_5": 1.84,
            "volume_ratio_20": 2.22,
        },
        "vwap": {
            "vwap": price + 420,
            "vwap_distance_pct": -0.14,
            "price_above_vwap": False,
        },
        "trend": {
            "ma5_crossed_above_ma20": False,
            "ma5_crossed_below_ma20": False,
            "consecutive_up_bars": 2,
            "consecutive_down_bars": 0,
        },
        "box_range": {
            "box_high": price + 1800,
            "box_low": price - 2200,
            "box_mid": price - 200,
            "current_price": price,
            "current_position_in_box": 0.55,
            "is_near_box_high": False,
            "is_near_box_low": False,
        },
        "recent_closes": [price - 500, price - 350, price - 100, price + 80, price],
        "recent_volumes": [8200, 9100, 11200, 14900, 18200],
    }

    events = [
        {"type": "VOLUME_SPIKE", "timeframe": "1m", "message": "Volume ratio spike", "value": 2.22},
        {"type": "NEAR_VWAP_RESISTANCE", "timeframe": "1m", "message": "Price is near VWAP", "value": -0.14},
    ]

    signal = {
        "action_hint": action,
        "confidence_score": 68,
        "risk_level": risk,
        "current_price": price,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "reasons": [
            "Event detected with volume expansion.",
            "VWAP and orderbook should be checked before action.",
        ],
    }

    return {
        "code": code,
        "name": name,
        "market_snapshot": {
            "trade_time": now.strftime("%H%M%S"),
            "current_price": price,
            "change_rate": 0.72,
            "acc_volume": 3240000,
            "day_open": round(price * 0.992),
            "day_high": round(price * 1.018),
            "day_low": round(price * 0.981),
            "strength": 142.3,
            "received_at": fmt(now),
        },
        "timeframes": {
            "1m": one_minute,
            "3m": dict(one_minute, bar_count=38),
            "5m": dict(one_minute, bar_count=24),
        },
        "market_context": make_market_context(now),
        "historical_price_context": make_historical_context(price, now),
        "historical_signal_stats": make_signal_stats(now),
        "events": events,
        "validation_signal": signal,
    }


def make_market_context(now):
    return {
        "market_status": {
            "asof": fmt(now),
            "market": "KOSPI",
            "market_phase": "regular",
            "sidecar_status": "inactive",
            "circuit_breaker_status": "inactive",
            "vi_status": "inactive",
            "summary": "Normal market operation.",
            "source": "manual_example",
            "reliability": "example",
        },
        "market_indices": {
            "kospi": 2815.59,
            "kospi_change_pct": 0.84,
            "kosdaq": 905.97,
            "kosdaq_change_pct": 0.47,
            "kospi200": 382.22,
            "kospi200_change_pct": 0.86,
        },
        "derivatives": {
            "kospi200_futures_price": 383.0,
            "basis": 0.78,
            "open_interest": 200763,
            "option_month": "202606",
            "call_option_volume": 14870,
            "put_option_volume": 23712,
            "put_call_ratio": 1.5946,
            "put_call_open_interest_ratio": 0.9568,
            "implied_volatility": 54.3965,
        },
        "short_selling": {
            "date": "20260522",
            "short_sale_volume": 423484,
            "short_sale_ratio_pct": 1.17,
            "stock_loan_balance_qty": 1182000,
            "stock_loan_balance_value": 351000000,
        },
        "credit": {
            "date": "20260521",
            "credit_balance_qty": 22775190,
            "credit_balance_ratio_pct": 0.38,
        },
        "investor_flow": {
            "date": "20260522",
            "individual_net_value": -1765364,
            "foreign_net_value": 1098673,
            "institution_net_value": 772880,
        },
        "orderbook": {
            "best_bid": 298000,
            "best_ask": 298500,
            "spread": 500,
            "bid_ask_imbalance": -0.42,
        },
        "market_program_trading": {
            "market": "KOSPI",
            "total_net_value": 2038664,
            "basis": 0.78,
        },
        "news": {
            "asof": fmt(now),
            "summary": "Example: sector news is neutral with no urgent disclosure.",
            "sentiment": "neutral",
            "source_count": 3,
            "items": [],
        },
        "disclosures": {
            "asof": fmt(now),
            "summary": "No material disclosure in this example.",
            "materiality": "none",
            "items": [],
        },
        "public_reaction": {
            "asof": fmt(now),
            "summary": "Retail community reaction is mixed; treat as low reliability.",
            "sentiment": "mixed",
            "weight": "very_low",
            "sample_size": 120,
        },
    }


def make_historical_context(price, now):
    return {
        "daily": {
            "timeframe": "day",
            "sample_size": 260,
            "latest_bar_time": now.strftime("%Y-%m-%d"),
            "latest_close": price,
            "return_20bar_pct": 4.21,
            "distance_from_20bar_high_pct": -2.14,
            "volume_ratio_20bar": 1.36,
        },
        "minute_1m": {"timeframe": "1m", "sample_size": 390, "return_20bar_pct": 0.82},
        "minute_3m": {"timeframe": "3m", "sample_size": 130, "return_20bar_pct": 1.15},
        "minute_5m": {"timeframe": "5m", "sample_size": 78, "return_20bar_pct": 0.64},
    }


def make_signal_stats(now):
    return {
        "asof": fmt(now),
        "sample_size": 44,
        "evaluated_count": 44,
        "avg_return_60m_pct": 0.368,
        "win_rate_60m_pct": 56.82,
        "stop_loss_hit_rate_pct": 25.0,
        "action_stats": [
            {
                "action_hint": "WATCH_PULLBACK",
                "sample_size": 12,
                "evaluated_count": 12,
                "avg_return_60m_pct": 0.42,
                "win_rate_60m_pct": 58.3,
            }
        ],
        "recent_signals": [],
    }


def make_paper_result(signal_id, code, price, now):
    return {
        "signal_id": signal_id,
        "evaluated_at": fmt(now + timedelta(minutes=60)),
        "code": code,
        "entry_time": fmt(now),
        "entry_price": price,
        "return_5m_pct": 0.18,
        "return_10m_pct": 0.24,
        "return_30m_pct": 0.31,
        "return_60m_pct": 0.46,
        "max_gain_30m_pct": 0.72,
        "max_loss_30m_pct": -0.28,
        "max_gain_60m_pct": 1.05,
        "max_loss_60m_pct": -0.44,
        "target_1_hit": True,
        "target_2_hit": False,
        "stop_loss_hit": False,
        "outcome_label": "target_1_hit",
    }


def add_gpt_logs(store, base_time):
    for idx in range(6):
        started = base_time + timedelta(minutes=idx * 3)
        finished = started + timedelta(seconds=12 + idx)
        store.save_gpt_call_log(
            started_at=fmt(started),
            finished_at=fmt(finished),
            status="success",
            requested_count=1 + (idx % 3),
            codes=["005930", "000660"][:1 + (idx % 2)],
            model="gpt-4o-mini-2024-07-18",
            duration_ms=int((finished - started).total_seconds() * 1000),
            prompt_chars=9200 + idx * 140,
            payload_original_chars=19541,
            payload_compressed_chars=8200 + idx * 80,
            payload_compression_ratio=0.42,
            prompt_tokens=3600 + idx * 45,
            completion_tokens=560 + idx * 12,
            total_tokens=4160 + idx * 57,
            result_preview="Example GPT analysis preview with cost-adjusted breakeven and PCR context.",
        )


def add_historical_bars(store, base_time):
    bars = []
    for code in WATCH_CODES:
        for idx in range(10):
            bar_time = (base_time - timedelta(days=idx)).strftime("%Y-%m-%d")
            bars.append({
                "code": code,
                "timeframe": "day",
                "bar_time": bar_time,
                "open": 100000 + idx * 100,
                "high": 101000 + idx * 100,
                "low": 99000 + idx * 100,
                "close": 100500 + idx * 100,
                "volume": 1200000 + idx * 10000,
                "trading_value": 300000000,
                "source": "example",
                "fetched_at": fmt(base_time),
            })
    store.save_historical_bars(bars)


def add_context_snapshots(store, base_time):
    context = make_market_context(base_time)
    for section in [
        "market_indices",
        "market_status",
        "derivatives",
        "market_program_trading",
        "news",
        "disclosures",
        "public_reaction",
    ]:
        store.save_market_context_snapshot(
            scope="global",
            section=section,
            payload=context[section],
            collected_at=fmt(base_time + timedelta(seconds=len(section))),
        )

    for code in WATCH_CODES:
        for section in ["short_selling", "credit", "investor_flow", "orderbook"]:
            store.save_market_context_snapshot(
                scope="code",
                code=code,
                section=section,
                payload=context[section],
                collected_at=fmt(base_time + timedelta(seconds=len(code) + len(section))),
            )


def make_gpt_text(name, code, price):
    return """# 실시간 종목 분석

## 1. 간결 분석
- 종목/코드: {name} / {code}
- 현재 판단: 대기
- 핵심 이벤트: 거래량 증가, VWAP 저항 근접, PCR 상승
- 비용 반영 손익분기: {breakeven}
- 가장 중요한 확인 조건: VWAP 돌파와 매도호가 불균형 해소
- 위험 요인: 대차잔고와 풋옵션 거래량 증가

## 2. 이벤트 상세 분석
- 수수료/세금/슬리피지를 반영하면 1차 목표가는 순수익이 작으므로 추격 진입 매력은 낮다.
- PCR과 IV는 시장 방어 심리를 보조적으로 시사한다.
- 공매도 거래와 대차잔고는 가격/거래량 신호를 약화시키는 보조 위험으로 본다.
""".format(name=name, code=code, breakeven=round(price * 1.0031, 2))


def capture_tab(dashboard, tab_name, path):
    for index in range(dashboard.tabs.count()):
        if dashboard.tabs.tabText(index) == tab_name:
            dashboard.tabs.setCurrentIndex(index)
            break
    dashboard.refresh_all()
    QApplication.processEvents()
    dashboard.grab().save(path)


def fmt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


if __name__ == "__main__":
    main()
