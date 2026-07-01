"""Generate validation signals from deterministic event combinations.

Signals are not trading orders. They are structured hypotheses that can be
saved, reviewed, and later evaluated by the paper-trade simulator.
"""

from datetime import datetime, time

from config import (
    SIGNAL_FOCUS_TIME_WINDOWS,
    SIGNAL_FOCUS_WINDOW_BONUS,
    SIGNAL_NON_FOCUS_WINDOW_PENALTY,
    SIGNAL_WEAK_TIME_WINDOWS,
    SIGNAL_WEAK_WINDOW_EXTRA_PENALTY,
    SIGNAL_MARKET_FLOW_RISK_PENALTY,
    ENABLE_RISK_ON_PULLBACK_RELABEL,
    SIGNAL_RISK_ON_MIN_MARKET_CHANGE_PCT,
    SIGNAL_RISK_ON_MIN_STOCK_CHANGE_PCT,
    SIGNAL_PULLBACK_MIN_CONFIRMING_VWAP_TIMEFRAMES,
    SIGNAL_PULLBACK_MACRO_EVENT_PENALTY,
    SIGNAL_PULLBACK_MACRO_EVENT_KEYWORDS,
    ENABLE_RISK_ON_RESISTANCE_RELABEL,
    SIGNAL_RESISTANCE_MIN_CONFIRMING_VWAP_TIMEFRAMES,
    SIGNAL_REQUIRE_RESISTANCE_CONFIRMATION,
    SIGNAL_REQUIRE_SUPPLY_CONFIRMATION,
    SIGNAL_HIGH_VOL_ATR_PCT,
    SIGNAL_EXTREME_VOL_ATR_PCT,
    SIGNAL_HIGH_VOL_BB_WIDTH_PCT,
    SIGNAL_EXTREME_VOL_BB_WIDTH_PCT,
    SIGNAL_HIGH_VOL_LEVEL_MULTIPLIER,
    SIGNAL_EXTREME_VOL_LEVEL_MULTIPLIER,
)
from signal_quality import apply_quality_tuning, pullback_stop_loss


def generate_validation_signal(summary, settings=None):
    """Return a watch/avoid signal when events form a meaningful setup."""
    events = summary.get("events") or []

    if not events:
        return None

    primary = _get_primary_timeframe(summary)
    latest = primary.get("latest", {})
    box_range = primary.get("box_range") or {}

    current_price = _to_float(latest.get("close"))
    box_high = _to_float(box_range.get("box_high"))
    box_low = _to_float(box_range.get("box_low"))
    event_types = set(event.get("type") for event in events)
    trend_state = _summarize_trend_state(summary)

    action_hint = "OBSERVE_EVENT"
    confidence_score = 50
    risk_level = "medium"
    reasons = []

    if "RSI_OVERSOLD" in event_types and "NEAR_BOX_LOW" in event_types:
        action_hint = "WATCH_REBOUND"
        confidence_score += 20
        risk_level = "medium"
        reasons.append("RSI oversold and price is near the lower box area.")

    if "NEAR_BOX_LOW" in event_types and "ORDERBOOK_BID_IMBALANCE" in event_types:
        action_hint = "WATCH_REBOUND"
        confidence_score += 18
        risk_level = "medium"
        reasons.append("Lower-box location with bid-side orderbook support can become a rebound setup.")

    if "NEAR_VWAP_SUPPORT" in event_types and "ORDERBOOK_BID_IMBALANCE" in event_types:
        action_hint = "WATCH_PULLBACK"
        confidence_score += 18
        risk_level = "medium"
        reasons.append("VWAP support with bid-side imbalance can become a pullback continuation setup.")

    if "VOLUME_SPIKE" in event_types and "NEAR_BOX_HIGH" in event_types:
        action_hint = "WATCH_BREAKOUT"
        confidence_score += 25
        risk_level = "high"
        reasons.append("Volume spike near the upper box area can become a breakout or a false breakout.")

    if "RSI_OVERBOUGHT" in event_types and "NEAR_BOX_HIGH" in event_types:
        action_hint = "AVOID_CHASE"
        confidence_score += 15
        risk_level = "high"
        reasons.append("RSI overbought near the upper box raises chase-buying risk.")

    if "NEAR_BOX_HIGH" in event_types and "VOLUME_SPIKE" not in event_types:
        action_hint = "AVOID_CHASE"
        confidence_score += 10
        risk_level = "high"
        reasons.append("Price is near the upper box without confirmed volume expansion.")

    if "MA5_MA20_GOLDEN_CROSS" in event_types:
        confidence_score += 5
        reasons.append("MA5 crossed above MA20.")

    if "MA5_MA20_DEAD_CROSS" in event_types:
        confidence_score += 5
        if risk_level == "medium":
            risk_level = "high"
        reasons.append("MA5 crossed below MA20.")

    if "NEAR_VWAP_SUPPORT" in event_types:
        confidence_score += 5
        if action_hint == "OBSERVE_EVENT":
            action_hint = "WATCH_SUPPORT"
        reasons.append("Price is close to VWAP support.")

    if "NEAR_VWAP_RESISTANCE" in event_types:
        risk_level = "high" if risk_level == "medium" else risk_level
        resistance_confirmed = _has_resistance_confirmation(event_types, trend_state)
        require_confirmation = _setting(
            settings,
            "SIGNAL_REQUIRE_RESISTANCE_CONFIRMATION",
            SIGNAL_REQUIRE_RESISTANCE_CONFIRMATION,
        )
        if action_hint == "OBSERVE_EVENT" and (resistance_confirmed or not require_confirmation):
            action_hint = "WATCH_RESISTANCE"
        elif action_hint == "OBSERVE_EVENT":
            confidence_score -= 8
            reasons.append(
                "VWAP resistance is unconfirmed; keep it as observation until supply or trend risk appears."
            )
        reasons.append("Price is close to VWAP resistance.")

    if "ORDERBOOK_BID_IMBALANCE" in event_types:
        confidence_score += 5
        reasons.append("Bid-side orderbook imbalance supports short-term demand.")

    if "ORDERBOOK_ASK_IMBALANCE" in event_types:
        risk_level = "high"
        supply_confirmed = _has_supply_confirmation(event_types, trend_state)
        require_confirmation = _setting(
            settings,
            "SIGNAL_REQUIRE_SUPPLY_CONFIRMATION",
            SIGNAL_REQUIRE_SUPPLY_CONFIRMATION,
        )
        if action_hint in ("OBSERVE_EVENT", "WATCH_SUPPORT", "WATCH_PULLBACK") and (
            supply_confirmed or not require_confirmation
        ):
            action_hint = "AVOID_SUPPLY"
        elif action_hint in ("WATCH_SUPPORT", "WATCH_PULLBACK"):
            action_hint = "OBSERVE_EVENT"
            confidence_score -= 10
            reasons.append(
                "Ask-side imbalance conflicts with support/pullback, but lacks confirmation for a supply-avoid signal."
            )
        elif not supply_confirmed and require_confirmation:
            confidence_score -= 8
            reasons.append("Ask-side imbalance alone is not enough to classify as avoid-supply.")
        reasons.append("Ask-side orderbook imbalance adds short-term supply risk.")

    if "CONSECUTIVE_UP_BARS" in event_types:
        confidence_score += 5
        if action_hint == "OBSERVE_EVENT":
            action_hint = "WATCH_MOMENTUM"
        reasons.append("Recent closes are rising consecutively.")

    if "CONSECUTIVE_DOWN_BARS" in event_types:
        confidence_score += 5
        if action_hint == "OBSERVE_EVENT":
            action_hint = "WATCH_PULLBACK"
        reasons.append("Recent closes are falling consecutively.")

    if "MARKET_SIDECAR_ACTIVE" in event_types:
        sidecar_direction = _market_sidecar_direction(summary)
        risk_level = "high"
        reasons.append("Market sidecar state requires broader market-risk adjustment.")

        if sidecar_direction == "sell":
            confidence_score -= 20
            if action_hint.startswith("WATCH_"):
                action_hint = "AVOID_MARKET_RISK"
            reasons.append(
                "Sell-side sidecar sharply reduces reliability of fresh long and rebound signals."
            )
        elif sidecar_direction == "buy":
            confidence_score -= 5
            reasons.append("Buy-side sidecar can be program-driven; avoid automatic rebound chasing.")
        else:
            confidence_score -= 10

    if "MARKET_SIDECAR_RECENT" in event_types:
        sidecar_direction = _market_sidecar_direction(summary)
        risk_level = "high"
        confidence_score -= 8
        reasons.append("A market sidecar occurred earlier today, so keep a session-level risk penalty.")

        if sidecar_direction == "sell" and action_hint in ("WATCH_REBOUND", "WATCH_BREAKOUT", "WATCH_SUPPORT"):
            confidence_score -= 7
            reasons.append("Recent sell-side sidecar weakens early rebound and breakout reliability.")

    if (
        "MARKET_CIRCUIT_BREAKER_ACTIVE" in event_types
        or "MARKET_CRASH_RISK" in event_types
        or "MARKET_VI_ACTIVE" in event_types
    ):
        action_hint = "AVOID_MARKET_RISK"
        confidence_score += 20
        risk_level = "high"
        reasons.append("Market-wide crash/interruption state makes normal signal reliability lower.")

    if "MARKET_FOREIGN_SELL_PRESSURE" in event_types:
        penalty = _setting(
            settings,
            "SIGNAL_MARKET_FLOW_RISK_PENALTY",
            SIGNAL_MARKET_FLOW_RISK_PENALTY
        )
        confidence_score -= _to_float(penalty) or 0
        risk_level = "high"
        reasons.append(
            "Market-wide foreign selling, program selling, and weak ETFs require a conservative discount."
        )

    if event_types == {"ORDERBOOK_BID_IMBALANCE"}:
        confidence_score = min(confidence_score, 45)
        risk_level = "medium"
        reasons.append("Bid-side orderbook imbalance alone is not enough for a long setup.")

    if trend_state["bearish_timeframes"] >= 2:
        confidence_score -= 15
        risk_level = "high"
        reasons.append(
            "At least two timeframes are bearish, so rebound/support signals need confirmation."
        )

        if action_hint in (
            "OBSERVE_EVENT",
            "WATCH_REBOUND",
            "WATCH_PULLBACK",
            "WATCH_SUPPORT",
            "WATCH_RESISTANCE",
            "WATCH_MOMENTUM",
        ):
            action_hint = "AVOID_DOWNTREND"

    if trend_state["below_vwap_timeframes"] >= 2 and trend_state["primary_consecutive_down"] >= 3:
        confidence_score -= 10
        risk_level = "high"
        reasons.append("Price is below VWAP on multiple timeframes with consecutive down bars.")

    if trend_state["bearish_timeframes"] >= 3:
        confidence_score = min(confidence_score, 45)
        reasons.append("All tracked timeframes are bearish; wait for trend reversal evidence.")

    action_hint, confidence_score, risk_level, reasons = _apply_risk_on_pullback_relabel(
        summary=summary,
        event_types=event_types,
        action_hint=action_hint,
        confidence_score=confidence_score,
        risk_level=risk_level,
        reasons=reasons,
        settings=settings,
    )

    action_hint, confidence_score, risk_level, reasons = _apply_pullback_safety_filter(
        summary=summary,
        event_types=event_types,
        trend_state=trend_state,
        action_hint=action_hint,
        confidence_score=confidence_score,
        risk_level=risk_level,
        reasons=reasons,
        settings=settings,
    )

    action_hint, confidence_score, risk_level, reasons = _apply_risk_on_resistance_relabel(
        summary=summary,
        event_types=event_types,
        trend_state=trend_state,
        action_hint=action_hint,
        confidence_score=confidence_score,
        risk_level=risk_level,
        reasons=reasons,
        settings=settings,
    )

    action_hint, confidence_score, risk_level, reasons = apply_quality_tuning(
        summary=summary,
        event_types=event_types,
        action_hint=action_hint,
        confidence_score=confidence_score,
        risk_level=risk_level,
        reasons=reasons,
    )

    confidence_score, reasons = _apply_time_window_adjustment(
        summary=summary,
        action_hint=action_hint,
        confidence_score=confidence_score,
        reasons=reasons,
        settings=settings,
    )

    action_hint, confidence_score, risk_level, reasons = _apply_volatility_action_split(
        summary=summary,
        event_types=event_types,
        trend_state=trend_state,
        action_hint=action_hint,
        confidence_score=confidence_score,
        risk_level=risk_level,
        reasons=reasons,
        settings=settings,
    )

    if not reasons:
        reasons.append("Event detected, but no strong validation pattern yet.")

    confidence_score = min(max(confidence_score, 0), 100)

    # Price levels are rough validation anchors, not executable order prices.
    stop_loss = _default_stop_loss(current_price, box_low)
    target_1 = _default_target_1(current_price, box_high)
    target_2 = _default_target_2(current_price, box_high)

    if action_hint == "WATCH_PULLBACK":
        stop_loss = pullback_stop_loss(current_price, stop_loss)

    stop_loss, target_1, target_2, volatility_note = _apply_volatility_level_adjustment(
        summary=summary,
        current_price=current_price,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        settings=settings,
    )
    if volatility_note:
        reasons.append(volatility_note)

    return {
        "action_hint": action_hint,
        "confidence_score": confidence_score,
        "risk_level": risk_level,
        "current_price": current_price,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "reasons": reasons,
    }

def _apply_time_window_adjustment(summary, action_hint, confidence_score, reasons, settings=None):
    """Apply conservative intraday score nudges without changing GPT call rules."""
    if not action_hint or not action_hint.startswith("WATCH_"):
        return confidence_score, reasons

    detected_time = _extract_detected_time(summary.get("detected_at"))

    if detected_time is None:
        return confidence_score, reasons

    settings = settings or {}
    focus_windows = settings.get("SIGNAL_FOCUS_TIME_WINDOWS", SIGNAL_FOCUS_TIME_WINDOWS)
    weak_windows = settings.get("SIGNAL_WEAK_TIME_WINDOWS", SIGNAL_WEAK_TIME_WINDOWS)
    focus_bonus = settings.get("SIGNAL_FOCUS_WINDOW_BONUS", SIGNAL_FOCUS_WINDOW_BONUS)
    non_focus_penalty = settings.get("SIGNAL_NON_FOCUS_WINDOW_PENALTY", SIGNAL_NON_FOCUS_WINDOW_PENALTY)
    weak_penalty = settings.get("SIGNAL_WEAK_WINDOW_EXTRA_PENALTY", SIGNAL_WEAK_WINDOW_EXTRA_PENALTY)

    in_focus = _time_in_windows(detected_time, focus_windows)
    in_weak = _time_in_windows(detected_time, weak_windows)

    if in_focus:
        confidence_score += _to_float(focus_bonus) or 0
        reasons.append("Signal occurred inside a preferred monitoring window.")
    else:
        confidence_score -= _to_float(non_focus_penalty) or 0
        reasons.append("Signal occurred outside the preferred monitoring windows.")

    if in_weak:
        confidence_score -= _to_float(weak_penalty) or 0
        reasons.append("This time window has weaker recent validation, so apply extra caution.")

    return confidence_score, reasons


def _apply_risk_on_pullback_relabel(
    summary,
    event_types,
    action_hint,
    confidence_score,
    risk_level,
    reasons,
    settings=None,
):
    """Treat mild downtrend labels as pullback watch signals in strong tapes."""
    enabled = _setting(
        settings,
        "ENABLE_RISK_ON_PULLBACK_RELABEL",
        ENABLE_RISK_ON_PULLBACK_RELABEL,
    )
    if not enabled or action_hint != "AVOID_DOWNTREND":
        return action_hint, confidence_score, risk_level, reasons

    hard_risk_events = {
        "MARKET_SIDECAR_ACTIVE",
        "MARKET_CIRCUIT_BREAKER_ACTIVE",
        "MARKET_CRASH_RISK",
        "MARKET_VI_ACTIVE",
        "MARKET_FOREIGN_SELL_PRESSURE",
        "NEAR_BOX_HIGH",
        "ORDERBOOK_ASK_IMBALANCE",
    }
    if event_types.intersection(hard_risk_events):
        return action_hint, confidence_score, risk_level, reasons

    if not _is_risk_on_pullback_context(summary, settings=settings):
        return action_hint, confidence_score, risk_level, reasons

    action_hint = "WATCH_PULLBACK"
    risk_level = "medium"
    confidence_score += 8
    reasons.append(
        "Risk-on market and positive stock tape turn the short-term downtrend into a pullback watch."
    )
    return action_hint, confidence_score, risk_level, reasons


def _apply_risk_on_resistance_relabel(
    summary,
    event_types,
    trend_state,
    action_hint,
    confidence_score,
    risk_level,
    reasons,
    settings=None,
):
    """Downgrade false resistance warnings in a confirmed risk-on tape."""
    enabled = _setting(
        settings,
        "ENABLE_RISK_ON_RESISTANCE_RELABEL",
        ENABLE_RISK_ON_RESISTANCE_RELABEL,
    )
    if not enabled or action_hint != "WATCH_RESISTANCE":
        return action_hint, confidence_score, risk_level, reasons

    if trend_state.get("bearish_timeframes", 0) > 0:
        return action_hint, confidence_score, risk_level, reasons

    if _has_hard_resistance_momentum_risk(event_types):
        return action_hint, confidence_score, risk_level, reasons

    required = int(_to_float(_setting(
        settings,
        "SIGNAL_RESISTANCE_MIN_CONFIRMING_VWAP_TIMEFRAMES",
        SIGNAL_RESISTANCE_MIN_CONFIRMING_VWAP_TIMEFRAMES,
    )) or 0)
    if _confirming_vwap_timeframes(summary) < required:
        return action_hint, confidence_score, risk_level, reasons

    if not _is_risk_on_pullback_context(summary, settings=settings):
        return action_hint, confidence_score, risk_level, reasons

    action_hint = "WATCH_MOMENTUM"
    risk_level = "medium"
    confidence_score += 6
    reasons.append(
        "Risk-on market and 3m/5m VWAP confirmation soften VWAP resistance into momentum observation."
    )
    return action_hint, confidence_score, risk_level, reasons


def _has_hard_resistance_momentum_risk(event_types):
    hard_events = {
        "MARKET_SIDECAR_ACTIVE",
        "MARKET_CIRCUIT_BREAKER_ACTIVE",
        "MARKET_CRASH_RISK",
        "MARKET_VI_ACTIVE",
        "MARKET_FOREIGN_SELL_PRESSURE",
        "ORDERBOOK_ASK_IMBALANCE",
    }
    return bool(event_types.intersection(hard_events))


def _has_resistance_confirmation(event_types, trend_state):
    """Return True when VWAP resistance has extra caution evidence."""
    confirming_events = {
        "NEAR_BOX_HIGH",
        "RSI_OVERBOUGHT",
        "ORDERBOOK_ASK_IMBALANCE",
        "MA5_MA20_DEAD_CROSS",
        "CONSECUTIVE_DOWN_BARS",
        "MARKET_FOREIGN_SELL_PRESSURE",
    }
    if event_types.intersection(confirming_events):
        return True
    if trend_state.get("bearish_timeframes", 0) >= 1:
        return True
    return False


def _has_supply_confirmation(event_types, trend_state):
    """Return True when ask-side pressure is supported by trend or flow risk."""
    confirming_events = {
        "MA5_MA20_DEAD_CROSS",
        "CONSECUTIVE_DOWN_BARS",
        "MARKET_FOREIGN_SELL_PRESSURE",
        "NEAR_BOX_HIGH",
        "RSI_OVERBOUGHT",
    }
    if event_types.intersection(confirming_events):
        return True
    if trend_state.get("bearish_timeframes", 0) >= 1:
        return True
    if trend_state.get("below_vwap_timeframes", 0) >= 2:
        return True
    return False


def _apply_pullback_safety_filter(
    summary,
    event_types,
    trend_state,
    action_hint,
    confidence_score,
    risk_level,
    reasons,
    settings=None,
):
    """Downgrade pullback watches when confirmation or macro safety is weak."""
    if action_hint != "WATCH_PULLBACK":
        return action_hint, confidence_score, risk_level, reasons

    if _has_hard_pullback_risk(summary, event_types, settings=settings):
        confidence_score -= _to_float(_setting(
            settings,
            "SIGNAL_PULLBACK_MACRO_EVENT_PENALTY",
            SIGNAL_PULLBACK_MACRO_EVENT_PENALTY,
        )) or 0
        risk_level = "high"
        reasons.append(
            "Pullback watch is downgraded because market flow or scheduled macro-event risk is high."
        )
        if trend_state.get("bearish_timeframes", 0) >= 2:
            return "AVOID_DOWNTREND", confidence_score, risk_level, reasons
        return "OBSERVE_EVENT", confidence_score, risk_level, reasons

    required = int(_to_float(_setting(
        settings,
        "SIGNAL_PULLBACK_MIN_CONFIRMING_VWAP_TIMEFRAMES",
        SIGNAL_PULLBACK_MIN_CONFIRMING_VWAP_TIMEFRAMES,
    )) or 0)
    confirming = _confirming_vwap_timeframes(summary)
    if confirming < required:
        confidence_score -= 10
        risk_level = "high"
        reasons.append(
            "Pullback watch lacks 3m/5m VWAP confirmation; treat as observation only."
        )
        if trend_state.get("bearish_timeframes", 0) >= 2:
            return "AVOID_DOWNTREND", confidence_score, risk_level, reasons
        return "OBSERVE_EVENT", confidence_score, risk_level, reasons

    return action_hint, confidence_score, risk_level, reasons


def _apply_volatility_action_split(
    summary,
    event_types,
    trend_state,
    action_hint,
    confidence_score,
    risk_level,
    reasons,
    settings=None,
):
    """Split elevated volatility into opportunity, reversal-watch, or trap labels."""
    if action_hint == "AVOID_MARKET_RISK":
        return action_hint, confidence_score, risk_level, reasons

    vol = _volatility_context(summary)
    level = _volatility_level(vol, settings=settings)
    if level == "normal":
        return action_hint, confidence_score, risk_level, reasons

    classification = _classify_volatility_setup(summary, event_types, trend_state)
    if classification == "trap":
        if action_hint.startswith("WATCH_") or action_hint == "OBSERVE_EVENT":
            action_hint = "AVOID_VOLATILITY_TRAP"
            confidence_score += 10
            risk_level = "high"
            reasons.append(
                "High volatility lacks directional confirmation or has supply risk; classify as volatility trap."
            )
        return action_hint, confidence_score, risk_level, reasons

    if classification == "reversal":
        action_hint = "HIGH_VOL_REVERSAL_WATCH"
        confidence_score += 6
        risk_level = "high"
        reasons.append(
            "High volatility still has risk, but VWAP recovery, volume, and market context support a reversal watch."
        )
        return action_hint, confidence_score, risk_level, reasons

    if classification != "opportunity":
        reasons.append("High volatility is present, but directional opportunity confirmation is incomplete.")
        return action_hint, confidence_score, "high", reasons

    if _is_volatility_breakout_context(summary, event_types):
        action_hint = "VOL_EXPANSION_MOMENTUM"
        confidence_score += 8
        risk_level = "high"
        reasons.append(
            "High volatility is aligned with volume, VWAP, trend, and market context; classify as expansion momentum."
        )
    elif _is_volatility_reversal_context(event_types, action_hint):
        action_hint = "HIGH_VOL_REVERSAL_WATCH"
        confidence_score += 6
        risk_level = "high"
        reasons.append(
            "High volatility has rebound ingredients after stress; classify as reversal watch, not immediate chase."
        )

    return action_hint, confidence_score, risk_level, reasons


def _classify_volatility_setup(summary, event_types, trend_state):
    hard_risk_events = {
        "MARKET_CIRCUIT_BREAKER_ACTIVE",
        "MARKET_CRASH_RISK",
        "MARKET_VI_ACTIVE",
        "MARKET_SIDECAR_ACTIVE",
    }
    supply_events = {
        "MARKET_FOREIGN_SELL_PRESSURE",
        "ORDERBOOK_ASK_IMBALANCE",
    }
    bullish_timeframes = _bullish_timeframes(summary)
    above_vwap = _price_above_vwap_timeframes(summary)
    volume_confirmed = _has_volume_confirmation(summary, event_types)
    market_score = _market_context_score(summary)
    market_risk_on = market_score >= 0

    if event_types.intersection(hard_risk_events):
        return "trap"

    if (
        event_types.intersection(supply_events)
        and _is_high_volatility_reversal_candidate(
            bullish_timeframes=bullish_timeframes,
            above_vwap=above_vwap,
            volume_confirmed=volume_confirmed,
            market_score=market_score,
            trend_state=trend_state,
        )
    ):
        return "reversal"

    if event_types.intersection(supply_events):
        return "trap"

    if (
        bullish_timeframes >= 2
        and above_vwap >= 2
        and volume_confirmed
        and market_risk_on
    ):
        return "opportunity"

    if trend_state.get("bearish_timeframes", 0) >= 2 or above_vwap <= 1:
        return "trap"

    return "unclear"


def _is_high_volatility_reversal_candidate(
    bullish_timeframes,
    above_vwap,
    volume_confirmed,
    market_score,
    trend_state,
):
    """Return True when elevated volatility looks like recoverable stress, not a trap."""
    if not volume_confirmed:
        return False
    if above_vwap < 2:
        return False
    if bullish_timeframes < 1:
        return False
    if market_score < 0:
        return False
    if trend_state.get("bearish_timeframes", 0) >= 3:
        return False
    return True


def _is_volatility_breakout_context(summary, event_types):
    return (
        ("VOLUME_SPIKE" in event_types or _has_volume_confirmation(summary, event_types))
        and (
            "NEAR_BOX_HIGH" in event_types
            or "CONSECUTIVE_UP_BARS" in event_types
            or _bullish_timeframes(summary) >= 2
        )
    )


def _is_volatility_reversal_context(event_types, action_hint):
    return (
        action_hint in ("WATCH_REBOUND", "WATCH_PULLBACK", "WATCH_SUPPORT")
        or bool(event_types.intersection(set((
            "RSI_OVERSOLD",
            "NEAR_BOX_LOW",
            "NEAR_VWAP_SUPPORT",
            "ORDERBOOK_BID_IMBALANCE",
        ))))
    )


def _bullish_timeframes(summary):
    count = 0
    for timeframe in (summary.get("timeframes") or {}).values():
        latest = timeframe.get("latest") or {}
        moving_average = timeframe.get("moving_average") or {}
        vwap = timeframe.get("vwap") or {}
        trend = timeframe.get("trend") or {}
        votes = 0
        return_1bar = _to_float(latest.get("return_1bar_pct"))
        if return_1bar is not None and return_1bar > 0:
            votes += 1
        if moving_average.get("price_above_ma5") is True:
            votes += 1
        if moving_average.get("price_above_ma20") is True:
            votes += 1
        if vwap.get("price_above_vwap") is True:
            votes += 1
        if (_to_float(trend.get("consecutive_up_bars")) or 0) >= 3:
            votes += 1
        if votes >= 3:
            count += 1
    return count


def _price_above_vwap_timeframes(summary):
    count = 0
    for timeframe in (summary.get("timeframes") or {}).values():
        if (timeframe.get("vwap") or {}).get("price_above_vwap") is True:
            count += 1
    return count


def _has_volume_confirmation(summary, event_types):
    if "VOLUME_SPIKE" in event_types:
        return True
    for timeframe in (summary.get("timeframes") or {}).values():
        volume = timeframe.get("volume") or {}
        ratio_5 = _to_float(volume.get("volume_ratio_5"))
        ratio_20 = _to_float(volume.get("volume_ratio_20"))
        if (ratio_5 is not None and ratio_5 >= 1.8) or (ratio_20 is not None and ratio_20 >= 1.8):
            return True
    return False


def _market_context_score(summary):
    market_context = summary.get("market_context") or {}
    market_indices = market_context.get("market_indices") or {}
    changes = []
    for key in (
        "kospi_change_pct",
        "kospi200_change_pct",
        "kosdaq_change_pct",
        "kosdaq150_change_pct",
        "kospi200_futures_change_pct",
    ):
        value = _to_float(market_indices.get(key))
        if value is not None:
            changes.append(value)
    if not changes:
        return 0
    return sum(changes) / float(len(changes))


def _has_hard_pullback_risk(summary, event_types, settings=None):
    hard_events = {
        "MARKET_SIDECAR_ACTIVE",
        "MARKET_CIRCUIT_BREAKER_ACTIVE",
        "MARKET_CRASH_RISK",
        "MARKET_VI_ACTIVE",
        "MARKET_FOREIGN_SELL_PRESSURE",
        "ORDERBOOK_ASK_IMBALANCE",
    }
    if event_types.intersection(hard_events):
        return True

    market_context = summary.get("market_context") or {}
    macro_context = market_context.get("macro_context") or {}
    if _has_high_impact_macro_event(macro_context, settings=settings):
        return True

    return False


def _confirming_vwap_timeframes(summary):
    timeframes = summary.get("timeframes") or {}
    count = 0
    for label in ("3m", "5m"):
        timeframe = timeframes.get(label) or {}
        vwap = timeframe.get("vwap") or {}
        if vwap.get("price_above_vwap") is True:
            count += 1
    return count


def _has_high_impact_macro_event(macro_context, settings=None):
    keywords = _setting(
        settings,
        "SIGNAL_PULLBACK_MACRO_EVENT_KEYWORDS",
        SIGNAL_PULLBACK_MACRO_EVENT_KEYWORDS,
    )
    lowered_keywords = [
        str(keyword).lower()
        for keyword in (keywords or [])
        if str(keyword).strip()
    ]
    if not lowered_keywords:
        return False

    for event in macro_context.get("next_macro_events") or []:
        event_text = _macro_event_text(event).lower()
        if any(keyword in event_text for keyword in lowered_keywords):
            return True

    return False


def _macro_event_text(event):
    if isinstance(event, dict):
        return " ".join(str(value) for value in event.values() if value is not None)
    return str(event)


def _is_risk_on_pullback_context(summary, settings=None):
    market_change_threshold = _to_float(_setting(
        settings,
        "SIGNAL_RISK_ON_MIN_MARKET_CHANGE_PCT",
        SIGNAL_RISK_ON_MIN_MARKET_CHANGE_PCT,
    ))
    stock_change_threshold = _to_float(_setting(
        settings,
        "SIGNAL_RISK_ON_MIN_STOCK_CHANGE_PCT",
        SIGNAL_RISK_ON_MIN_STOCK_CHANGE_PCT,
    ))

    market_snapshot = summary.get("market_snapshot") or {}
    stock_change = _to_float(market_snapshot.get("change_rate"))
    if stock_change is None or stock_change < stock_change_threshold:
        return False

    market_context = summary.get("market_context") or {}
    market_indices = market_context.get("market_indices") or {}
    index_changes = [
        _to_float(market_indices.get("kospi200_change_pct")),
        _to_float(market_indices.get("kospi_change_pct")),
        _to_float(market_indices.get("kosdaq_change_pct")),
    ]
    if any(value is not None and value >= market_change_threshold for value in index_changes):
        return True

    benchmark_etfs = market_context.get("benchmark_etfs") or {}
    for item in benchmark_etfs.values():
        if not isinstance(item, dict):
            continue
        change = _to_float(item.get("change_rate") or item.get("change_pct"))
        if change is not None and change >= market_change_threshold:
            return True

    return False


def _extract_detected_time(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value.time()

    text = str(value).strip()

    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue

    return None


def _time_in_windows(value, windows):
    for window in windows or []:
        start, end = _parse_time_window(window)
        if start is None or end is None:
            continue

        if start <= end and start <= value < end:
            return True
        if start > end and (value >= start or value < end):
            return True

    return False


def _parse_time_window(window):
    try:
        start_text, end_text = str(window).split("-", 1)
        return _parse_clock(start_text), _parse_clock(end_text)
    except ValueError:
        return None, None


def _parse_clock(value):
    try:
        hour_text, minute_text = str(value).strip().split(":", 1)
        return time(int(hour_text), int(minute_text))
    except (TypeError, ValueError):
        return None


def _get_primary_timeframe(summary):
    """Use 1m as the signal source when multi-timeframe data is present."""
    timeframes = summary.get("timeframes") or {}

    if timeframes.get("1m"):
        return timeframes["1m"]

    for timeframe_summary in timeframes.values():
        return timeframe_summary

    return summary


def _summarize_trend_state(summary):
    """Return compact multi-timeframe trend state for signal risk adjustment."""
    timeframes = summary.get("timeframes") or {}
    bearish_timeframes = 0
    below_vwap_timeframes = 0
    primary_consecutive_down = 0

    for label in ("1m", "3m", "5m"):
        timeframe = timeframes.get(label) or {}
        latest = timeframe.get("latest") or {}
        moving_average = timeframe.get("moving_average") or {}
        vwap = timeframe.get("vwap") or {}
        trend = timeframe.get("trend") or {}

        return_1bar = _to_float(latest.get("return_1bar_pct"))
        consecutive_down = _to_float(trend.get("consecutive_down_bars")) or 0
        bearish_votes = 0

        if return_1bar is not None and return_1bar < 0:
            bearish_votes += 1
        if moving_average.get("price_above_ma5") is False:
            bearish_votes += 1
        if moving_average.get("price_above_ma20") is False:
            bearish_votes += 1
        if vwap.get("price_above_vwap") is False:
            bearish_votes += 1
            below_vwap_timeframes += 1
        if consecutive_down >= 3:
            bearish_votes += 1

        if bearish_votes >= 3:
            bearish_timeframes += 1

        if label == "1m":
            primary_consecutive_down = int(consecutive_down)

    return {
        "bearish_timeframes": bearish_timeframes,
        "below_vwap_timeframes": below_vwap_timeframes,
        "primary_consecutive_down": primary_consecutive_down,
    }


def _market_sidecar_direction(summary):
    """Read the current market-wide sidecar direction from GPT context."""
    market_context = summary.get("market_context") or {}
    market_status = market_context.get("market_status") or {}
    direction = market_status.get("sidecar_direction")
    if direction is None:
        return None
    return str(direction).strip().lower()


def _default_stop_loss(current_price, box_low):
    """Prefer lower box as stop; otherwise use a simple fallback percent."""
    if current_price is None:
        return None

    if box_low is not None and box_low < current_price:
        return round(box_low, 2)

    return round(current_price * 0.985, 2)


def _default_target_1(current_price, box_high):
    """Prefer upper box as first target; otherwise use a simple fallback percent."""
    if current_price is None:
        return None

    if box_high is not None and box_high > current_price:
        return round(box_high, 2)

    return round(current_price * 1.015, 2)


def _default_target_2(current_price, box_high):
    """Project a second target beyond the box or use a fallback percent."""
    if current_price is None:
        return None

    if box_high is not None and box_high > current_price:
        return round(box_high + (box_high - current_price), 2)

    return round(current_price * 1.03, 2)


def _apply_volatility_level_adjustment(
    summary,
    current_price,
    stop_loss,
    target_1,
    target_2,
    settings=None,
):
    """Widen paper-validation anchors when intraday volatility is elevated."""
    if current_price is None:
        return stop_loss, target_1, target_2, None

    vol = _volatility_context(summary)
    level = _volatility_level(vol, settings=settings)
    if level == "normal":
        return stop_loss, target_1, target_2, None

    multiplier = _to_float(_setting(
        settings,
        "SIGNAL_EXTREME_VOL_LEVEL_MULTIPLIER" if level == "extreme" else "SIGNAL_HIGH_VOL_LEVEL_MULTIPLIER",
        SIGNAL_EXTREME_VOL_LEVEL_MULTIPLIER if level == "extreme" else SIGNAL_HIGH_VOL_LEVEL_MULTIPLIER,
    )) or 1.0

    stop_loss = _widen_downside_level(current_price, stop_loss, multiplier)
    target_1 = _widen_upside_level(current_price, target_1, multiplier)
    target_2 = _widen_upside_level(current_price, target_2, multiplier)
    note = (
        "High-volatility session widened paper validation anchors "
        "(level={}, atr_pct={}, bb_width_pct={}, multiplier={})."
    ).format(
        level,
        _round_or_none(vol.get("atr_pct")),
        _round_or_none(vol.get("bb_width_pct")),
        multiplier,
    )
    return stop_loss, target_1, target_2, note


def _widen_downside_level(current_price, level, multiplier):
    fallback_distance_pct = 1.5
    if level is not None and level < current_price:
        distance_pct = (current_price - level) / current_price * 100.0
    else:
        distance_pct = fallback_distance_pct
    adjusted_pct = max(distance_pct * multiplier, fallback_distance_pct * multiplier)
    return round(current_price * (1 - adjusted_pct / 100.0), 2)


def _widen_upside_level(current_price, level, multiplier):
    fallback_distance_pct = 1.5
    if level is not None and level > current_price:
        distance_pct = (level - current_price) / current_price * 100.0
    else:
        distance_pct = fallback_distance_pct
    adjusted_pct = max(distance_pct * multiplier, fallback_distance_pct * multiplier)
    return round(current_price * (1 + adjusted_pct / 100.0), 2)


def _volatility_context(summary):
    atr_values = []
    bb_width_values = []
    for timeframe in (summary.get("timeframes") or {}).values():
        volatility = timeframe.get("volatility") or {}
        atr = _to_float(volatility.get("atr14_pct"))
        bb_width = _to_float(volatility.get("bb_width_pct"))
        if atr is not None:
            atr_values.append(atr)
        if bb_width is not None:
            bb_width_values.append(bb_width)
    return {
        "atr_pct": max(atr_values) if atr_values else None,
        "bb_width_pct": max(bb_width_values) if bb_width_values else None,
    }


def _volatility_level(volatility, settings=None):
    atr_pct = volatility.get("atr_pct")
    bb_width_pct = volatility.get("bb_width_pct")
    extreme_atr = _to_float(_setting(settings, "SIGNAL_EXTREME_VOL_ATR_PCT", SIGNAL_EXTREME_VOL_ATR_PCT))
    high_atr = _to_float(_setting(settings, "SIGNAL_HIGH_VOL_ATR_PCT", SIGNAL_HIGH_VOL_ATR_PCT))
    extreme_bb = _to_float(_setting(settings, "SIGNAL_EXTREME_VOL_BB_WIDTH_PCT", SIGNAL_EXTREME_VOL_BB_WIDTH_PCT))
    high_bb = _to_float(_setting(settings, "SIGNAL_HIGH_VOL_BB_WIDTH_PCT", SIGNAL_HIGH_VOL_BB_WIDTH_PCT))

    if (
        (atr_pct is not None and extreme_atr is not None and atr_pct >= extreme_atr)
        or (bb_width_pct is not None and extreme_bb is not None and bb_width_pct >= extreme_bb)
    ):
        return "extreme"
    if (
        (atr_pct is not None and high_atr is not None and atr_pct >= high_atr)
        or (bb_width_pct is not None and high_bb is not None and bb_width_pct >= high_bb)
    ):
        return "high"
    return "normal"


def _round_or_none(value):
    if value is None:
        return None
    return round(value, 3)


def _to_float(value):
    """Best-effort numeric conversion for indicator values."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _setting(settings, key, default):
    """Read a runtime setting while preserving the config default."""
    if not settings:
        return default
    return settings.get(key, default)
