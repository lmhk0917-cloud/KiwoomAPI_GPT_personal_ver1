"""Deterministic quant score snapshots for validation signals.

This score is not an order signal. It records the rule-engine view at the
moment a signal is created so it can later be compared with GPT scores and
paper-trade outcomes.
"""

from datetime import datetime

from config import (
    QUANT_EXTREME_VOL_CAUTION_BONUS,
    QUANT_EXTREME_VOL_LONG_PENALTY,
    QUANT_HIGH_VOL_CAUTION_BONUS,
    QUANT_HIGH_VOL_LONG_PENALTY,
    QUANT_VOL_OPPORTUNITY_CAUTION_DISCOUNT,
    QUANT_VOL_OPPORTUNITY_LONG_BONUS,
    QUANT_VOL_TRAP_CAUTION_BONUS,
    QUANT_VOL_TRAP_LONG_PENALTY,
    SIGNAL_EXTREME_VOL_ATR_PCT,
    SIGNAL_EXTREME_VOL_BB_WIDTH_PCT,
    SIGNAL_HIGH_VOL_ATR_PCT,
    SIGNAL_HIGH_VOL_BB_WIDTH_PCT,
    TRADE_BUY_FEE_PCT,
    TRADE_SELL_FEE_PCT,
    TRADE_SELL_TAX_PCT,
    TRADE_SLIPPAGE_PCT,
)


FORMULA_VERSION = "quant_signal_score_v2"
ROUND_TRIP_COST_PCT = (
    TRADE_BUY_FEE_PCT
    + TRADE_SELL_FEE_PCT
    + TRADE_SELL_TAX_PCT
    + (TRADE_SLIPPAGE_PCT * 2)
)

LONG_ACTIONS = set((
    "WATCH_REBOUND",
    "WATCH_PULLBACK",
    "WATCH_BREAKOUT",
    "WATCH_SUPPORT",
    "WATCH_MOMENTUM",
    "VOL_EXPANSION_MOMENTUM",
    "HIGH_VOL_REVERSAL_WATCH",
))
CAUTION_ACTIONS = set((
    "AVOID_CHASE",
    "AVOID_DOWNTREND",
    "AVOID_SUPPLY",
    "WATCH_RESISTANCE",
    "OBSERVE_EVENT",
    "AVOID_MARKET_RISK",
    "AVOID_VOLATILITY_TRAP",
))
HIGH_RISK_EVENTS = set((
    "MARKET_FOREIGN_SELL_PRESSURE",
    "MARKET_SIDECAR_ACTIVE",
    "MARKET_CIRCUIT_BREAKER_ACTIVE",
    "MARKET_CRASH_RISK",
    "MARKET_VI_ACTIVE",
    "ORDERBOOK_ASK_IMBALANCE",
))
HARD_OVERRIDE_EVENTS = set((
    "MARKET_CIRCUIT_BREAKER_ACTIVE",
    "MARKET_CRASH_RISK",
    "MARKET_VI_ACTIVE",
))

MIN_FEEDBACK_SAMPLE = 10


def build_quant_signal_score(signal, summary, signal_id=None, scored_at=None):
    """Build a structured deterministic score row from one signal and summary."""
    signal = signal or {}
    summary = summary or {}
    scored_at = scored_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    action_hint = signal.get("action_hint")
    event_types = _event_types(summary)
    decision_side = _decision_side(action_hint)

    sub_scores, reasons = _build_sub_scores(signal, summary, event_types, decision_side)
    long_score, caution_score, feedback_reasons = _side_scores(
        signal=signal,
        summary=summary,
        sub_scores=sub_scores,
        decision_side=decision_side,
        action_hint=action_hint,
    )
    reasons.extend(feedback_reasons)
    if decision_side == "long_candidate":
        final_quant_score = long_score
    elif decision_side == "caution_or_avoid":
        final_quant_score = caution_score
    else:
        final_quant_score = _clip((long_score + caution_score) / 2)

    hard_overrides = _hard_overrides(summary, event_types)
    if hard_overrides:
        decision_side = "caution_or_avoid"
        action_hint = "AVOID_MARKET_RISK"
        final_quant_score = min(final_quant_score, 25)
        caution_score = max(caution_score, 85)
        long_score = min(long_score, 20)
        sub_scores["market_regime_score"] = min(sub_scores["market_regime_score"], 10)
        sub_scores["risk_reward_score"] = min(sub_scores["risk_reward_score"], 20)
        reasons.append(
            "Market-wide crash/interruption state overrides normal technical setup quality."
        )

    market_risk_score = _market_risk_score(sub_scores, event_types, signal.get("risk_level"))
    quant_signal_score = _clip(
        0.35 * sub_scores["trend_score"]
        + 0.30 * sub_scores["breakout_score"]
        + 0.20 * sub_scores["volume_flow_score"]
        + 0.15 * _clip(_number(signal.get("confidence_score"), 50))
    )

    features = _feature_snapshot(
        signal=signal,
        summary=summary,
        sub_scores=sub_scores,
        hard_overrides=hard_overrides,
        reasons=reasons,
        final_quant_score=final_quant_score,
        long_score=long_score,
        caution_score=caution_score,
        score_confidence=_score_confidence(summary, action_hint),
    )
    return {
        "signal_id": signal_id,
        "scored_at": scored_at,
        "code": summary.get("code") or signal.get("code"),
        "action_hint": action_hint,
        "quant_signal_score": quant_signal_score,
        "expected_value_score": sub_scores["expected_value_score"],
        "market_risk_score": market_risk_score,
        "final_quant_score": final_quant_score,
        "decision_side": decision_side,
        "feature_json": features,
        "formula_version": FORMULA_VERSION,
    }


def _build_sub_scores(signal, summary, event_types, decision_side):
    reasons = []
    trend_counts = _trend_counts(summary)
    trend_score = _trend_score(summary, trend_counts, reasons)
    breakout_score = _breakout_score(summary, event_types, reasons)
    volume_flow_score = _volume_flow_score(summary, event_types, reasons)
    expected_value_score = _expected_value_score(summary, reasons)
    market_regime_score = _market_regime_score(summary, event_types, reasons)
    risk_reward_score = _risk_reward_score(signal, event_types, reasons)
    gpt_agreement_score = _gpt_agreement_score(summary, decision_side, reasons)
    risk_penalty = _risk_penalty(summary, event_types, trend_counts)
    cost_penalty = _cost_penalty(signal)
    return {
        "trend_score": trend_score,
        "breakout_score": breakout_score,
        "volume_flow_score": volume_flow_score,
        "expected_value_score": expected_value_score,
        "market_regime_score": market_regime_score,
        "risk_reward_score": risk_reward_score,
        "gpt_agreement_score": gpt_agreement_score,
        "risk_penalty": risk_penalty,
        "cost_penalty": cost_penalty,
    }, reasons


def _side_scores(signal, summary, sub_scores, decision_side, action_hint):
    """Return separate long-quality and caution-quality scores.

    Long score is intentionally stricter because recent paper results show that
    candidate-long actions lose money after costs unless feedback is strong.
    Caution score measures risk-warning usefulness, not long-entry quality.
    """
    reasons = []
    risk_penalty = sub_scores["risk_penalty"]
    cost_penalty = sub_scores["cost_penalty"]
    market_risk = _market_risk_score(sub_scores, _event_types(summary), signal.get("risk_level"))
    volatility = _volatility_adjustment(summary)

    long_score = (
        0.22 * sub_scores["trend_score"]
        + 0.18 * sub_scores["breakout_score"]
        + 0.16 * sub_scores["volume_flow_score"]
        + 0.20 * sub_scores["expected_value_score"]
        + 0.10 * sub_scores["market_regime_score"]
        + 0.10 * sub_scores["risk_reward_score"]
        + 0.04 * sub_scores["gpt_agreement_score"]
        - risk_penalty
        - cost_penalty
    )
    caution_score = (
        0.30 * market_risk
        + 0.20 * (100 - sub_scores["expected_value_score"])
        + 0.18 * (100 - sub_scores["trend_score"])
        + 0.12 * (100 - sub_scores["volume_flow_score"])
        + 0.10 * (100 - sub_scores["market_regime_score"])
        + 0.05 * (100 - sub_scores["risk_reward_score"])
        + 0.05 * sub_scores["gpt_agreement_score"]
        + 0.40 * risk_penalty
    )

    if volatility["classification"] == "opportunity":
        long_score += volatility["opportunity_long_bonus"]
        caution_score -= volatility["opportunity_caution_discount"]
        reasons.append(
            "Volatility expansion has directional confirmation, so treat it as opportunity context."
        )
    elif volatility["classification"] == "reversal":
        long_score += volatility["reversal_long_bonus"]
        caution_score -= volatility["reversal_caution_discount"]
        reasons.append(
            "Volatility stress has recovery confirmation, so track it as reversal-watch context."
        )
    elif volatility["classification"] == "trap":
        long_score -= volatility["trap_long_penalty"]
        caution_score += volatility["trap_caution_bonus"]
        reasons.append(
            "Volatility expansion lacks confirmation or has supply risk, so treat it as trap context."
        )
    elif volatility["level"] != "normal":
        long_score -= volatility["long_penalty"]
        caution_score += volatility["caution_bonus"]
        reasons.append(
            "Elevated intraday volatility adds long-score penalty and caution-score bonus."
        )

    action_feedback = _action_feedback(summary, action_hint)
    overview = (_quant_snapshot(summary).get("overview") or {})
    feedback_block = action_feedback or overview
    feedback_sample = _number(feedback_block.get("evaluated_60m_count"))
    if feedback_sample is None:
        feedback_sample = _number(feedback_block.get("evaluated_count"), 0)
    net60 = _first_number(feedback_block, ("avg_net_return_60m_pct", "expectancy_60m_pct"))
    win60 = _number(feedback_block.get("win_rate_60m_pct"))
    directional60 = _number(feedback_block.get("directional_success_60m_pct"))
    stop_rate = _number(feedback_block.get("stop_loss_hit_rate_pct"))

    if feedback_sample < MIN_FEEDBACK_SAMPLE:
        long_score -= 8
        caution_score += 4
        reasons.append("Action feedback sample is below long-score threshold.")
    if net60 is not None and net60 < 0:
        penalty = min(18, abs(net60) * 24)
        long_score -= penalty
        caution_score += min(12, penalty * 0.7)
        reasons.append("Action feedback has negative 60m net expectancy.")
    elif net60 is not None and net60 > 0:
        bonus = min(10, net60 * 18)
        long_score += bonus
        caution_score -= min(8, bonus * 0.6)
    if win60 is not None and win60 < 45:
        long_score -= 8
    if stop_rate is not None and stop_rate >= 50:
        long_score -= min(14, (stop_rate - 45) * 0.45)
        caution_score += min(12, (stop_rate - 45) * 0.35)
        reasons.append("Stop-hit rate is too high for a permissive long score.")
    if directional60 is not None:
        if decision_side == "long_candidate" and directional60 < 50:
            long_score -= min(12, (50 - directional60) * 0.45)
        elif decision_side == "caution_or_avoid" and directional60 >= 55:
            caution_score += min(10, (directional60 - 50) * 0.35)
        elif decision_side == "caution_or_avoid" and directional60 < 40:
            caution_score -= min(12, (40 - directional60) * 0.45)
            reasons.append("Caution action has recently missed upside.")

    if decision_side == "long_candidate":
        long_score -= 5
    if action_hint in ("WATCH_SUPPORT", "WATCH_PULLBACK") and (net60 is None or net60 <= 0):
        long_score -= 6
        reasons.append("Support/pullback requires positive net feedback before promotion.")

    return _clip(long_score), _clip(caution_score), reasons


def _trend_score(summary, trend_counts, reasons):
    bullish = trend_counts.get("bullish", 0)
    bearish = trend_counts.get("bearish", 0)
    primary = _primary_timeframe(summary)
    moving_average = primary.get("moving_average") or {}
    vwap = primary.get("vwap") or {}
    trend = primary.get("trend") or {}
    score = 25 + (bullish * 18) - (bearish * 14)

    if moving_average.get("price_above_ma5") is True:
        score += 6
    if moving_average.get("price_above_ma20") is True:
        score += 7
    if vwap.get("price_above_vwap") is True:
        score += 8
    if _number(trend.get("consecutive_up_bars"), 0) >= 3:
        score += 8
    if _number(trend.get("consecutive_down_bars"), 0) >= 3:
        score -= 12
    if bearish >= 2:
        score -= 18
        reasons.append("Two or more timeframes are bearish.")
    if bullish >= 2:
        reasons.append("Multiple timeframes confirm bullish trend.")
    return _clip(score)


def _breakout_score(summary, event_types, reasons):
    primary = _primary_timeframe(summary)
    box_range = primary.get("box_range") or {}
    position = _number(box_range.get("current_position_in_box"))
    score = 35

    if "NEAR_BOX_HIGH" in event_types:
        score += 14
    if "NEAR_BOX_LOW" in event_types:
        score += 10
    if "VOLUME_SPIKE" in event_types:
        score += 18
    if "NEAR_VWAP_SUPPORT" in event_types:
        score += 12
    if "NEAR_VWAP_RESISTANCE" in event_types:
        score -= 10
    if "ORDERBOOK_BID_IMBALANCE" in event_types:
        score += 10
    if "ORDERBOOK_ASK_IMBALANCE" in event_types:
        score -= 15
    if "NEAR_BOX_HIGH" in event_types and "VOLUME_SPIKE" not in event_types:
        score -= 18
        reasons.append("Upper-box setup lacks volume confirmation.")
    if position is not None and 0.15 <= position <= 0.85:
        score -= 5
    return _clip(score)


def _volume_flow_score(summary, event_types, reasons):
    primary = _primary_timeframe(summary)
    volume = primary.get("volume") or {}
    market_context = summary.get("market_context") or {}
    market_flow = market_context.get("market_investor_flow") or {}
    market_program = market_context.get("market_program_trading") or {}
    market_indices = market_context.get("market_indices") or {}

    ratio_5 = _number(volume.get("volume_ratio_5"))
    ratio_20 = _number(volume.get("volume_ratio_20"))
    max_ratio = max([value for value in (ratio_5, ratio_20) if value is not None] or [None])
    foreign_net = _number(market_flow.get("combined_foreign_net_value"))
    program_net = _number(market_program.get("total_net_value"))
    index_changes = _market_index_changes(market_indices)
    avg_index_change = _avg(index_changes)

    score = 45
    if max_ratio is not None:
        score += min(max(max_ratio - 1.0, 0) * 12, 22)
    if "ORDERBOOK_BID_IMBALANCE" in event_types:
        score += 12
    if "ORDERBOOK_ASK_IMBALANCE" in event_types:
        score -= 16
    if foreign_net is not None:
        score += 10 if foreign_net > 0 else -12
    if program_net is not None:
        score += 8 if program_net > 0 else -10
    if avg_index_change is not None:
        score += max(min(avg_index_change * 4, 12), -20)
    if "MARKET_FOREIGN_SELL_PRESSURE" in event_types:
        score = min(score, 45)
        score -= 18
        reasons.append("Broad foreign/program sell pressure caps volume-flow quality.")
    return _clip(score)


def _expected_value_score(summary, reasons=None):
    quant_snapshot = _quant_snapshot(summary)
    overview = quant_snapshot.get("overview") or {}
    net10 = _first_number(overview, ("avg_net_return_10m_pct", "avg_return_10m_pct"))
    net30 = _first_number(overview, ("avg_net_return_30m_pct", "avg_return_30m_pct"))
    net60 = _first_number(overview, ("avg_net_return_60m_pct", "avg_return_60m_pct"))
    profit_factor = _number(overview.get("profit_factor_60m"))
    directional = _number(overview.get("directional_success_60m_pct"))
    evaluated = _number(overview.get("evaluated_count"), 0)
    label = (quant_snapshot.get("guidance") or {}).get("label")

    score = 50
    if net10 is not None:
        score += 12 * net10
    if net30 is not None:
        score += 18 * net30
    if net60 is not None:
        score += 20 * net60
    if profit_factor is not None:
        score += 10 * (profit_factor - 1)
    if directional is not None:
        score += 0.15 * (directional - 50)
    if evaluated < 5:
        score -= 20
        if reasons is not None:
            reasons.append("Paper-trade sample is below 5.")
    elif evaluated < 10:
        score -= 10
    if label == "negative_expectancy":
        score = min(score, 45)
        if reasons is not None:
            reasons.append("Recent paper feedback is negative expectancy.")
    return _clip(score)


def _market_regime_score(summary, event_types, reasons):
    market_context = summary.get("market_context") or {}
    market_indices = market_context.get("market_indices") or {}
    index_changes = _market_index_changes(market_indices)
    avg_index_change = _avg(index_changes)
    score = 70

    if avg_index_change is not None:
        if avg_index_change > 1.0:
            score += 15
        elif avg_index_change < -1.0:
            score += max(avg_index_change * 6, -35)
    if "MARKET_FOREIGN_SELL_PRESSURE" in event_types:
        score -= 25
    if "MARKET_CRASH_RISK" in event_types:
        score -= 35
        reasons.append("Market crash risk is active.")
    if "MARKET_CIRCUIT_BREAKER_ACTIVE" in event_types or "MARKET_VI_ACTIVE" in event_types:
        score -= 60
        reasons.append("Market interruption state is active or inferred.")
    if "MARKET_SIDECAR_ACTIVE" in event_types:
        score -= 25
    if _market_context_stale(market_context):
        score -= 5
        reasons.append("Market context appears stale.")
    return _clip(score)


def _risk_reward_score(signal, event_types, reasons):
    entry = _number(signal.get("current_price"))
    stop = _number(signal.get("stop_loss"))
    target_1 = _number(signal.get("target_1"))
    target_2 = _number(signal.get("target_2"))
    if not entry or not stop or not target_1 or stop >= entry or target_1 <= entry:
        reasons.append("Risk/reward inputs are incomplete or invalid.")
        return 35

    reward_1 = (target_1 - entry) / entry * 100.0
    reward_2 = ((target_2 - entry) / entry * 100.0) if target_2 and target_2 > entry else reward_1
    risk = (entry - stop) / entry * 100.0
    weighted_reward = 0.65 * reward_1 + 0.35 * reward_2
    rr = weighted_reward / max(risk, 0.01)
    score = 35 * min(rr / 2.0, 1.0)
    score += 25 if reward_1 > ROUND_TRIP_COST_PCT * 2 else 10
    score += 20 if risk <= max(weighted_reward, 0.01) else 8
    score += 20 if weighted_reward - ROUND_TRIP_COST_PCT > 0 else 5
    if event_types.intersection(HARD_OVERRIDE_EVENTS):
        score = min(score, 20)
    return _clip(score)


def _gpt_agreement_score(summary, decision_side, reasons):
    gpt = (
        summary.get("gpt_score")
        or summary.get("gpt_analysis_score")
        or summary.get("latest_gpt_score")
        or {}
    )
    if not gpt:
        reasons.append("GPT score is not available; neutral agreement score used.")
        return 50

    decision = str(gpt.get("decision") or "").lower()
    risk_score = _number(gpt.get("risk_score"), 50)
    confidence = _number(gpt.get("confidence"), 50)
    gpt_side = _gpt_decision_side(decision)
    score = 50
    if gpt_side != "unknown" and gpt_side == decision_side:
        score += 20
    elif gpt_side != "unknown" and gpt_side != decision_side:
        score -= 20
    score -= 0.20 * max(risk_score - 60, 0)
    score += 0.10 * max(confidence - 50, 0)
    return _clip(score)


def _risk_penalty(summary, event_types, trend_state):
    penalty = 0
    if "MARKET_CIRCUIT_BREAKER_ACTIVE" in event_types or "MARKET_VI_ACTIVE" in event_types:
        penalty += 25
    if "MARKET_CRASH_RISK" in event_types:
        penalty += 20
    if "MARKET_FOREIGN_SELL_PRESSURE" in event_types:
        penalty += 12
    if trend_state["bearish"] >= 2:
        penalty += 10
    if "ORDERBOOK_ASK_IMBALANCE" in event_types:
        penalty += 8
    if "RSI_OVERBOUGHT" in event_types and "NEAR_BOX_HIGH" in event_types:
        penalty += 6
    if _market_context_stale((summary.get("market_context") or {})):
        penalty += 5
    return _clip(penalty)


def _cost_penalty(signal):
    penalty = min(15, ROUND_TRIP_COST_PCT * 10)
    entry = _number(signal.get("current_price"))
    target_1 = _number(signal.get("target_1"))
    if entry and target_1 and target_1 > entry:
        reward_1 = (target_1 - entry) / entry * 100.0
        if reward_1 < ROUND_TRIP_COST_PCT * 2:
            penalty += 5
    return _clip(penalty)


def _market_risk_score(sub_scores, event_types, risk_level):
    score = {"low": 20, "medium": 45, "high": 70}.get(str(risk_level or "").lower(), 50)
    score += 8 * len(event_types.intersection(HIGH_RISK_EVENTS))
    score += 0.35 * sub_scores.get("risk_penalty", 0)
    score += 0.20 * (100 - sub_scores.get("market_regime_score", 50))
    return _clip(score)


def _feature_snapshot(
    signal,
    summary,
    sub_scores,
    hard_overrides,
    reasons,
    final_quant_score,
    long_score,
    caution_score,
    score_confidence,
):
    primary = _primary_timeframe(summary)
    latest = primary.get("latest") or {}
    volume = primary.get("volume") or {}
    vwap = primary.get("vwap") or {}
    moving_average = primary.get("moving_average") or {}
    trend = primary.get("trend") or {}
    volatility = _volatility_adjustment(summary)
    quant_snapshot = _quant_snapshot(summary)
    return {
        "formula_version": FORMULA_VERSION,
        "events": [event.get("type") for event in summary.get("events") or []],
        "risk_level": signal.get("risk_level"),
        "score_label": _score_label(final_quant_score, hard_overrides),
        "long_score": long_score,
        "caution_score": caution_score,
        "score_confidence": score_confidence,
        "sub_scores": sub_scores,
        "hard_overrides": hard_overrides,
        "score_reasons": _dedupe(reasons)[:8],
        "current_price": signal.get("current_price"),
        "stop_loss": signal.get("stop_loss"),
        "target_1": signal.get("target_1"),
        "target_2": signal.get("target_2"),
        "return_1bar_pct": latest.get("return_1bar_pct"),
        "volume_ratio_5": volume.get("volume_ratio_5"),
        "volume_ratio_20": volume.get("volume_ratio_20"),
        "vwap_distance_pct": vwap.get("vwap_distance_pct"),
        "price_above_vwap": vwap.get("price_above_vwap"),
        "price_above_ma5": moving_average.get("price_above_ma5"),
        "price_above_ma20": moving_average.get("price_above_ma20"),
        "consecutive_up_bars": trend.get("consecutive_up_bars"),
        "consecutive_down_bars": trend.get("consecutive_down_bars"),
        "volatility_level": volatility.get("level"),
        "volatility_atr_pct": volatility.get("atr_pct"),
        "volatility_bb_width_pct": volatility.get("bb_width_pct"),
        "volatility_long_penalty": volatility.get("long_penalty"),
        "volatility_caution_bonus": volatility.get("caution_bonus"),
        "volatility_classification": volatility.get("classification"),
        "volatility_opportunity_score": volatility.get("opportunity_score"),
        "volatility_trap_score": volatility.get("trap_score"),
        "quant_feedback_label": (quant_snapshot.get("guidance") or {}).get("label"),
        "quant_feedback_net_60m": (quant_snapshot.get("overview") or {}).get("avg_net_return_60m_pct"),
        "quant_feedback_profit_factor_60m": (quant_snapshot.get("overview") or {}).get("profit_factor_60m"),
        "action_feedback": _action_feedback(summary, signal.get("action_hint")) or {},
    }


def _hard_overrides(summary, event_types):
    overrides = sorted(event_types.intersection(HARD_OVERRIDE_EVENTS))
    if "MARKET_SIDECAR_ACTIVE" in event_types and _market_sidecar_direction(summary) == "sell":
        overrides.append("SELL_SIDE_MARKET_SIDECAR_ACTIVE")
    return overrides


def _score_label(score, hard_overrides):
    if hard_overrides:
        return "Avoid Market Risk"
    if score >= 80:
        return "Strong Watch"
    if score >= 65:
        return "Watch"
    if score >= 50:
        return "Observe"
    if score >= 35:
        return "Caution"
    return "Avoid"


def _timeframe_state(timeframe):
    latest = timeframe.get("latest") or {}
    moving_average = timeframe.get("moving_average") or {}
    vwap = timeframe.get("vwap") or {}
    bullish_votes = 0
    bearish_votes = 0
    return_1bar = _number(latest.get("return_1bar_pct"))
    if return_1bar is not None:
        if return_1bar > 0:
            bullish_votes += 1
        elif return_1bar < 0:
            bearish_votes += 1
    for value in (
        moving_average.get("price_above_ma5"),
        moving_average.get("price_above_ma20"),
        vwap.get("price_above_vwap"),
    ):
        if value is True:
            bullish_votes += 1
        elif value is False:
            bearish_votes += 1
    if bullish_votes >= 2 and bullish_votes > bearish_votes:
        return "bullish"
    if bearish_votes >= 2 and bearish_votes > bullish_votes:
        return "bearish"
    return "neutral"


def _trend_counts(summary):
    timeframes = summary.get("timeframes") or {}
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for label in ("1m", "3m", "5m"):
        counts[_timeframe_state(timeframes.get(label) or {})] += 1
    return counts


def _market_index_changes(market_indices):
    changes = []
    for key in (
        "kospi_change_pct",
        "kospi200_change_pct",
        "kosdaq_change_pct",
        "kosdaq150_change_pct",
        "kospi200_futures_change_pct",
    ):
        value = _number(market_indices.get(key))
        if value is not None:
            changes.append(value)
    return changes


def _market_context_stale(market_context):
    market_status = market_context.get("market_status") or {}
    summary = str(market_status.get("summary") or "")
    source = str(market_status.get("source") or "")
    return "gap-fill" in summary.lower() or "manual_gapfill" in source


def _market_sidecar_direction(summary):
    market_context = summary.get("market_context") or {}
    market_status = market_context.get("market_status") or {}
    direction = market_status.get("sidecar_direction")
    if direction is None:
        return None
    return str(direction).strip().lower()


def _volatility_adjustment(summary):
    atr_values = []
    bb_width_values = []
    for timeframe in (summary.get("timeframes") or {}).values():
        volatility = timeframe.get("volatility") or {}
        atr_pct = _number(volatility.get("atr14_pct"))
        bb_width_pct = _number(volatility.get("bb_width_pct"))
        if atr_pct is not None:
            atr_values.append(atr_pct)
        if bb_width_pct is not None:
            bb_width_values.append(bb_width_pct)

    atr_pct = max(atr_values) if atr_values else None
    bb_width_pct = max(bb_width_values) if bb_width_values else None
    level = "normal"
    if (
        (atr_pct is not None and atr_pct >= SIGNAL_EXTREME_VOL_ATR_PCT)
        or (bb_width_pct is not None and bb_width_pct >= SIGNAL_EXTREME_VOL_BB_WIDTH_PCT)
    ):
        level = "extreme"
    elif (
        (atr_pct is not None and atr_pct >= SIGNAL_HIGH_VOL_ATR_PCT)
        or (bb_width_pct is not None and bb_width_pct >= SIGNAL_HIGH_VOL_BB_WIDTH_PCT)
    ):
        level = "high"

    classification, opportunity_score, trap_score = _volatility_classification(summary, level)

    if level == "extreme":
        long_penalty = QUANT_EXTREME_VOL_LONG_PENALTY
        caution_bonus = QUANT_EXTREME_VOL_CAUTION_BONUS
    elif level == "high":
        long_penalty = QUANT_HIGH_VOL_LONG_PENALTY
        caution_bonus = QUANT_HIGH_VOL_CAUTION_BONUS
    else:
        long_penalty = 0
        caution_bonus = 0

    return {
        "level": level,
        "atr_pct": round(atr_pct, 3) if atr_pct is not None else None,
        "bb_width_pct": round(bb_width_pct, 3) if bb_width_pct is not None else None,
        "long_penalty": long_penalty,
        "caution_bonus": caution_bonus,
        "classification": classification,
        "opportunity_score": opportunity_score,
        "trap_score": trap_score,
        "opportunity_long_bonus": QUANT_VOL_OPPORTUNITY_LONG_BONUS,
        "opportunity_caution_discount": QUANT_VOL_OPPORTUNITY_CAUTION_DISCOUNT,
        "reversal_long_bonus": round(QUANT_VOL_OPPORTUNITY_LONG_BONUS * 0.75, 3),
        "reversal_caution_discount": round(QUANT_VOL_OPPORTUNITY_CAUTION_DISCOUNT * 0.75, 3),
        "trap_long_penalty": QUANT_VOL_TRAP_LONG_PENALTY,
        "trap_caution_bonus": QUANT_VOL_TRAP_CAUTION_BONUS,
    }


def _volatility_classification(summary, level):
    if level == "normal":
        return "normal", 0, 0

    event_types = _event_types(summary)
    trend_counts = _trend_counts(summary)
    vwap_confirming = _price_above_vwap_timeframes(summary)
    volume_score = _volatility_volume_score(summary, event_types)
    market_score = _volatility_market_score(summary)
    hard_risk = bool(event_types.intersection(HARD_OVERRIDE_EVENTS))
    supply_risk = bool(event_types.intersection(set((
        "MARKET_FOREIGN_SELL_PRESSURE",
        "ORDERBOOK_ASK_IMBALANCE",
    ))))

    opportunity_score = 0
    opportunity_score += 25 if trend_counts.get("bullish", 0) >= 2 else 0
    opportunity_score += 20 if vwap_confirming >= 2 else 0
    opportunity_score += volume_score
    opportunity_score += market_score
    opportunity_score += 15 if "VOLUME_SPIKE" in event_types else 0

    trap_score = 0
    trap_score += 35 if hard_risk else 0
    trap_score += 22 if supply_risk else 0
    trap_score += 20 if trend_counts.get("bearish", 0) >= 2 else 0
    trap_score += 15 if vwap_confirming <= 1 else 0
    trap_score += 10 if market_score < 0 else 0

    if (
        supply_risk
        and not hard_risk
        and vwap_confirming >= 2
        and volume_score >= 12
        and trend_counts.get("bullish", 0) >= 1
        and trend_counts.get("bearish", 0) < 3
        and market_score >= 0
    ):
        return "reversal", min(opportunity_score, 100), min(trap_score, 100)

    if opportunity_score >= 55 and trap_score < 35:
        return "opportunity", min(opportunity_score, 100), min(trap_score, 100)
    if trap_score >= 35:
        return "trap", min(opportunity_score, 100), min(trap_score, 100)
    return "unclear", min(opportunity_score, 100), min(trap_score, 100)


def _price_above_vwap_timeframes(summary):
    count = 0
    for timeframe in (summary.get("timeframes") or {}).values():
        if (timeframe.get("vwap") or {}).get("price_above_vwap") is True:
            count += 1
    return count


def _volatility_volume_score(summary, event_types):
    ratios = []
    for timeframe in (summary.get("timeframes") or {}).values():
        volume = timeframe.get("volume") or {}
        for key in ("volume_ratio_5", "volume_ratio_20"):
            value = _number(volume.get(key))
            if value is not None:
                ratios.append(value)
    max_ratio = max(ratios) if ratios else None
    if max_ratio is None:
        return 15 if "VOLUME_SPIKE" in event_types else 0
    return min(max((max_ratio - 1.0) * 18, 0), 25)


def _volatility_market_score(summary):
    market_context = summary.get("market_context") or {}
    market_indices = market_context.get("market_indices") or {}
    avg_change = _avg(_market_index_changes(market_indices))
    if avg_change is None:
        return 0
    return max(min(avg_change * 10, 20), -20)


def _quant_snapshot(summary):
    return (
        ((summary.get("historical_signal_stats") or {}).get("learning_feedback") or {})
        .get("quant_snapshot")
        or {}
    )


def _action_feedback(summary, action_hint):
    if not action_hint:
        return None
    for item in (_quant_snapshot(summary).get("by_action") or []):
        if item.get("action_hint") == action_hint:
            return item
    return None


def _score_confidence(summary, action_hint):
    action_feedback = _action_feedback(summary, action_hint)
    overview = (_quant_snapshot(summary).get("overview") or {})
    feedback = action_feedback or overview
    evaluated = _number(feedback.get("evaluated_60m_count"))
    if evaluated is None:
        evaluated = _number(feedback.get("evaluated_count"), 0)
    if evaluated >= 100:
        return "high"
    if evaluated >= MIN_FEEDBACK_SAMPLE:
        return "medium"
    if evaluated > 0:
        return "low"
    return "unknown"


def _primary_timeframe(summary):
    timeframes = summary.get("timeframes") or {}
    for key in ("1m", "3m", "5m"):
        if timeframes.get(key):
            return timeframes.get(key) or {}
    return {}


def _event_types(summary):
    return set(event.get("type") for event in summary.get("events") or [])


def _decision_side(action_hint):
    if action_hint in LONG_ACTIONS:
        return "long_candidate"
    if action_hint in CAUTION_ACTIONS:
        return "caution_or_avoid"
    return "unknown"


def _gpt_decision_side(decision):
    if decision in ("watch", "consider", "long_candidate", "buy_watch"):
        return "long_candidate"
    if decision in ("avoid", "observe", "caution", "reject"):
        return "caution_or_avoid"
    return "unknown"


def _first_number(data, keys):
    for key in keys:
        value = _number(data.get(key))
        if value is not None:
            return value
    return None


def _number(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _avg(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / float(len(values))


def _clip(value):
    value = _number(value, 0)
    return round(min(max(value, 0), 100), 4)


def _dedupe(values):
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
