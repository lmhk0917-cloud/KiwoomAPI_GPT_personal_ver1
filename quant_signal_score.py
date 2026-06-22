"""Deterministic quant score snapshots for validation signals.

This score is not an order signal. It records the rule-engine view at the
moment a signal is created so it can later be compared with GPT scores and
paper-trade outcomes.
"""

from datetime import datetime


FORMULA_VERSION = "quant_signal_score_v1"
LONG_ACTIONS = set((
    "WATCH_REBOUND",
    "WATCH_PULLBACK",
    "WATCH_BREAKOUT",
    "WATCH_SUPPORT",
    "WATCH_MOMENTUM",
))
CAUTION_ACTIONS = set((
    "AVOID_CHASE",
    "AVOID_DOWNTREND",
    "AVOID_SUPPLY",
    "WATCH_RESISTANCE",
    "OBSERVE_EVENT",
    "AVOID_MARKET_RISK",
))
HIGH_RISK_EVENTS = set((
    "MARKET_FOREIGN_SELL_PRESSURE",
    "MARKET_SIDECAR_ACTIVE",
    "MARKET_CIRCUIT_BREAKER_ACTIVE",
    "MARKET_VI_ACTIVE",
    "ORDERBOOK_ASK_IMBALANCE",
))


def build_quant_signal_score(signal, summary, signal_id=None, scored_at=None):
    """Build a structured deterministic score row from one signal and summary."""
    signal = signal or {}
    summary = summary or {}
    scored_at = scored_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    action_hint = signal.get("action_hint")
    quant_signal_score = _clip(_number(signal.get("confidence_score"), 0))
    risk_level = signal.get("risk_level")
    expected_value_score = _expected_value_score(summary)
    market_risk_score = _market_risk_score(summary, risk_level)
    final_quant_score = _clip(
        0.50 * quant_signal_score
        + 0.30 * expected_value_score
        + 0.20 * (100 - market_risk_score)
    )

    features = _feature_snapshot(signal, summary)
    return {
        "signal_id": signal_id,
        "scored_at": scored_at,
        "code": summary.get("code") or signal.get("code"),
        "action_hint": action_hint,
        "quant_signal_score": quant_signal_score,
        "expected_value_score": expected_value_score,
        "market_risk_score": market_risk_score,
        "final_quant_score": final_quant_score,
        "decision_side": _decision_side(action_hint),
        "feature_json": features,
        "formula_version": FORMULA_VERSION,
    }


def _feature_snapshot(signal, summary):
    primary = _primary_timeframe(summary)
    latest = primary.get("latest") or {}
    volume = primary.get("volume") or {}
    vwap = primary.get("vwap") or {}
    moving_average = primary.get("moving_average") or {}
    trend = primary.get("trend") or {}
    quant_snapshot = (
        ((summary.get("historical_signal_stats") or {}).get("learning_feedback") or {})
        .get("quant_snapshot")
        or {}
    )
    return {
        "events": [event.get("type") for event in summary.get("events") or []],
        "risk_level": signal.get("risk_level"),
        "current_price": signal.get("current_price"),
        "return_1bar_pct": latest.get("return_1bar_pct"),
        "volume_ratio_5": volume.get("volume_ratio_5"),
        "volume_ratio_20": volume.get("volume_ratio_20"),
        "vwap_distance_pct": vwap.get("vwap_distance_pct"),
        "price_above_vwap": vwap.get("price_above_vwap"),
        "price_above_ma5": moving_average.get("price_above_ma5"),
        "price_above_ma20": moving_average.get("price_above_ma20"),
        "consecutive_up_bars": trend.get("consecutive_up_bars"),
        "consecutive_down_bars": trend.get("consecutive_down_bars"),
        "quant_feedback_label": (quant_snapshot.get("guidance") or {}).get("label"),
        "quant_feedback_net_60m": (quant_snapshot.get("overview") or {}).get("avg_net_return_60m_pct"),
        "quant_feedback_profit_factor_60m": (quant_snapshot.get("overview") or {}).get("profit_factor_60m"),
    }


def _expected_value_score(summary):
    quant_snapshot = (
        ((summary.get("historical_signal_stats") or {}).get("learning_feedback") or {})
        .get("quant_snapshot")
        or {}
    )
    overview = quant_snapshot.get("overview") or {}
    net60 = overview.get("avg_net_return_60m_pct")
    profit_factor = overview.get("profit_factor_60m")
    score = 50
    if net60 is not None:
        score += _number(net60, 0) * 20
    if profit_factor is not None:
        score += (_number(profit_factor, 1) - 1) * 15
    return _clip(score)


def _market_risk_score(summary, risk_level):
    score = {"low": 20, "medium": 45, "high": 70}.get(str(risk_level or "").lower(), 50)
    event_types = set(event.get("type") for event in summary.get("events") or [])
    score += 8 * len(event_types.intersection(HIGH_RISK_EVENTS))
    return _clip(score)


def _primary_timeframe(summary):
    timeframes = summary.get("timeframes") or {}
    for key in ("1m", "3m", "5m"):
        if timeframes.get(key):
            return timeframes.get(key) or {}
    return {}


def _decision_side(action_hint):
    if action_hint in LONG_ACTIONS:
        return "long_candidate"
    if action_hint in CAUTION_ACTIONS:
        return "caution_or_avoid"
    return "unknown"


def _number(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value):
    value = _number(value, 0)
    return round(min(max(value, 0), 100), 4)
