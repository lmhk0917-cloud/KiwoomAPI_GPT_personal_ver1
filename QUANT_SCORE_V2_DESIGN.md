# Quant Score v2 Design

## Goal

Quant Score v2 is a paper-trade validation score, not an order signal. It should
rank fixed-watchlist events by risk/reward quality, explain why a signal is weak
or strong, and make GPT review more auditable.

The score must keep the project scope:

- No live order placement.
- No broad market screening.
- GPT remains a risk/reward evaluator, not a buy instructor.
- Hard market-risk states override attractive technical scores.
- Every sub-score must be stored so UI and feedback reports can explain the result.

## Current v1 Baseline

Current formula in `quant_signal_score.py`:

```text
final_quant_score =
  0.50 * quant_signal_score
+ 0.30 * expected_value_score
+ 0.20 * (100 - market_risk_score)
```

Limitations:

- `quant_signal_score` mostly mirrors rule-engine confidence.
- Trend, breakout, volume/flow, market regime, and risk/reward are not separated.
- UI cannot explain which component caused a weak score.
- Circuit-breaker-level sessions are now detected, but v1 only applies a broad risk penalty.

## v2 Output Contract

Keep existing DB columns unchanged for compatibility:

- `quant_signal_score`
- `expected_value_score`
- `market_risk_score`
- `final_quant_score`
- `decision_side`
- `feature_json`
- `formula_version`

Use:

```text
formula_version = quant_signal_score_v2
```

Store v2 details inside `feature_json`:

```json
{
  "formula_version": "quant_signal_score_v2",
  "sub_scores": {
    "trend_score": 0,
    "breakout_score": 0,
    "volume_flow_score": 0,
    "expected_value_score": 0,
    "market_regime_score": 0,
    "risk_reward_score": 0,
    "gpt_agreement_score": null,
    "risk_penalty": 0,
    "cost_penalty": 0
  },
  "hard_overrides": [],
  "score_reasons": []
}
```

## Final Formula

Base formula:

```text
raw_score =
  0.25 * TrendScore
+ 0.20 * BreakoutScore
+ 0.15 * VolumeFlowScore
+ 0.15 * ExpectedValueScore
+ 0.10 * MarketRegimeScore
+ 0.10 * RiskRewardScore
+ 0.05 * GPTAgreementScore
- RiskPenalty
- CostPenalty

final_quant_score = clip(raw_score, 0, 100)
```

If GPT is not available yet for the signal:

```text
GPTAgreementScore = 50
```

This keeps GPT low-weight and prevents missing GPT data from distorting the quant score.

## Hard Overrides

Hard overrides run after sub-score calculation and before final decision labels.

If any of these events exist:

- `MARKET_CIRCUIT_BREAKER_ACTIVE`
- `MARKET_CRASH_RISK`
- `MARKET_VI_ACTIVE`
- sell-side `MARKET_SIDECAR_ACTIVE`

Then:

```text
decision_side = caution_or_avoid
action_hint = AVOID_MARKET_RISK
final_quant_score = min(final_quant_score, 25)
market_regime_score = min(market_regime_score, 10)
```

Reason:

```text
Market-wide crash/interruption state overrides normal technical setup quality.
```

## Sub-Score Definitions

### TrendScore

Inputs:

- 1m/3m/5m `return_1bar_pct`
- price above MA5/MA20
- price above VWAP
- consecutive up/down bars
- MA5/MA20 cross events

Formula:

```text
TrendScore =
  20 * TF1_Bullish
+ 20 * TF3_Bullish
+ 20 * TF5_Bullish
+ 15 * MA_Alignment
+ 15 * VWAP_Alignment
+ 10 * MomentumPersistence
- 20 * MultiTF_BearishPenalty
```

Boolean components use 0 or 1. Partial values are allowed when only one of MA/VWAP
confirms.

Guidance:

- `TFx_Bullish = 1` when at least two of return, MA, VWAP are positive.
- `MA_Alignment = 1` when price is above MA5 and MA20 on primary timeframe.
- `VWAP_Alignment = 1` when 1m and at least one of 3m/5m are above VWAP.
- `MomentumPersistence = 1` for confirmed consecutive up bars, 0.5 for neutral.
- `MultiTF_BearishPenalty = 1` when at least two timeframes are bearish.

### BreakoutScore

Inputs:

- box position
- near box high/low events
- VWAP support/resistance events
- volume spike
- false-breakout risk events

Formula:

```text
BreakoutScore =
  25 * BoxBreakOrSupport
+ 20 * VolumeConfirmed
+ 20 * VWAPRecoverOrHold
+ 15 * OrderbookSupport
+ 10 * VolatilityExpansion
+ 10 * CleanRetest
- 25 * FalseBreakoutRisk
```

Guidance:

- Rebound/support candidates can score through `BoxBreakOrSupport`.
- Resistance without volume confirmation should not become a strong long score.
- `ORDERBOOK_ASK_IMBALANCE`, `NEAR_BOX_HIGH` without volume, or downtrend confirmation
  increase `FalseBreakoutRisk`.

### VolumeFlowScore

Inputs:

- volume ratio 5/20
- orderbook imbalance
- foreign net flow
- program trading net flow
- weak benchmark ETF count
- market index direction

Formula:

```text
VolumeFlowScore =
  25 * VolumeExpansion
+ 20 * OrderbookDemand
+ 20 * ForeignFlowSupport
+ 15 * ProgramFlowSupport
+ 10 * BenchmarkETFSupport
+ 10 * IndexDirectionSupport
- 30 * BroadSellPressure
```

Guidance:

- `MARKET_FOREIGN_SELL_PRESSURE` sets `BroadSellPressure = 1`.
- Unknown flow fields should be neutral, not bullish.
- Negative foreign/program flow should cap this score at 45.

### ExpectedValueScore

Inputs:

- recent paper-trade `avg_net_return_5m/10m/30m/60m`
- `profit_factor_60m`
- directional success
- evaluated sample count
- action/code-specific feedback snapshot

Base formula:

```text
ExpectedValueScore =
  50
+ 12 * avg_net_return_10m_pct
+ 18 * avg_net_return_30m_pct
+ 20 * avg_net_return_60m_pct
+ 10 * (profit_factor_60m - 1)
+ 0.15 * (directional_success_60m_pct - 50)
- SamplePenalty
```

Sample penalty:

```text
SamplePenalty =
  20 if evaluated_count < 5
  10 if evaluated_count < 10
   0 otherwise
```

Guidance:

- Clip to 0-100.
- Negative expectancy labels should cap this score at 45 unless current setup has
  strong non-paper confirmation.
- This score should be computed per code/action when available, then fall back to
  code-level, then global.

### MarketRegimeScore

Inputs:

- market status sidecar/circuit/VI
- inferred market crash risk from index snapshots
- KOSPI/KOSPI200/KOSDAQ change pct
- macro context and scheduled high-impact events

Formula:

```text
MarketRegimeScore =
  70
+ 15 * RiskOnIndexTape
+ 10 * MacroSupport
- 25 * ForeignProgramSellPressure
- 35 * MarketCrashRisk
- 60 * CircuitBreakerOrVI
- 15 * HighImpactMacroEventSoon
```

Guidance:

- Circuit breaker, VI, and crash risk are hard overrides.
- Stale `market_context.json` must not create bullish macro support.
- Missing macro context should be neutral.

### RiskRewardScore

Inputs:

- current price
- stop loss
- target 1
- target 2
- target/stop scenario validation
- holding horizon bucket

Formula:

```text
reward_1 = (target_1 - entry) / entry * 100
reward_2 = (target_2 - entry) / entry * 100
risk = (entry - stop_loss) / entry * 100
rr = weighted_reward / max(risk, 0.01)

RiskRewardScore =
  35 * min(rr / 2.0, 1)
+ 25 * TargetFirstRate
+ 20 * (1 - StopFirstRate)
+ 20 * PositiveScenarioEV
```

Weighted reward:

```text
weighted_reward = 0.65 * reward_1 + 0.35 * reward_2
```

Use scenario data from `target_exit_scenarios.py`:

- 10m target 0.3 / stop 0.4
- 30m target 0.5 / stop 0.5
- 30m target 0.8 / stop 0.6
- 60m target 0.8 / stop 0.6
- 60m target 1.0 / stop 0.8

Guidance:

- If stop/target values are invalid, set score to 35 and add a reason.
- If market crash hard override is active, cap RiskRewardScore at 20.

### GPTAgreementScore

Inputs:

- latest GPT decision for same code/signal window
- GPT risk score
- GPT confidence
- GPT context score

Formula:

```text
GPTAgreementScore =
  50
+ 20 if GPT decision agrees with quant decision side
- 20 if GPT decision conflicts with quant decision side
- 0.20 * max(GPT risk_score - 60, 0)
+ 0.10 * max(GPT confidence - 50, 0)
```

Guidance:

- Clip to 0-100.
- Keep final weight at 5%.
- GPT should be allowed to flag risks, not force a high quant score.
- If no GPT row exists, use neutral 50 and reason `gpt_not_available`.

## Penalties

### RiskPenalty

```text
RiskPenalty =
  25 * CircuitBreakerOrVI
+ 20 * MarketCrashRisk
+ 12 * MarketForeignSellPressure
+ 10 * MultiTFBearish
+ 8  * AskImbalance
+ 6  * OverboughtChase
+ 5  * StaleMarketContext
```

### CostPenalty

Use existing config:

```text
round_trip_cost_pct =
  TRADE_BUY_FEE_PCT
+ TRADE_SELL_FEE_PCT
+ TRADE_SELL_TAX_PCT
+ 2 * TRADE_SLIPPAGE_PCT
```

Formula:

```text
CostPenalty = min(15, round_trip_cost_pct * 10)
```

If target 1 reward is less than twice round-trip cost:

```text
CostPenalty += 5
```

## Decision Labels

Use score labels for UI. These are not trade instructions.

```text
80-100  Strong Watch
65-79   Watch
50-64   Observe
35-49   Caution
0-34    Avoid
```

Hard override label:

```text
Avoid Market Risk
```

Decision side:

```text
long_candidate:
  WATCH_REBOUND, WATCH_PULLBACK, WATCH_BREAKOUT, WATCH_SUPPORT, WATCH_MOMENTUM

caution_or_avoid:
  AVOID_CHASE, AVOID_DOWNTREND, AVOID_SUPPLY, WATCH_RESISTANCE,
  OBSERVE_EVENT, AVOID_MARKET_RISK
```

## UI Requirements

UI should display the score as an audit panel, not as a buy signal.

Minimum fields:

- Final score and label.
- Hard override badge, if present.
- Six sub-scores: Trend, Breakout, Volume/Flow, Expected Value, Market Regime, Risk/Reward.
- Penalties: Risk, Cost.
- GPT agreement score.
- Top 3 positive reasons.
- Top 3 negative reasons.
- Paper feedback horizon used: 5m/10m/30m/60m.
- Last updated timestamps: tick, analysis, GPT, quant score.

Recommended table columns:

```text
time | code | action | label | final | trend | breakout | volume/flow |
EV | regime | RR | risk penalty | GPT agree | override
```

## Implementation Plan

1. Add v2 helper functions inside `quant_signal_score.py`.
2. Keep `build_quant_signal_score()` public API unchanged.
3. Set `FORMULA_VERSION = "quant_signal_score_v2"`.
4. Store v2 sub-scores and reasons in `feature_json`.
5. Keep existing DB schema unchanged.
6. Extend `tests/test_quant_signal_score.py` for:
   - normal watch candidate,
   - negative paper feedback,
   - market crash hard override,
   - missing GPT neutral score,
   - invalid stop/target fallback.
7. Update dashboard/UI to read `feature_json.sub_scores`.
8. Run:
   - `python -m unittest tests.test_quant_signal_score`
   - `python -m unittest discover -s tests`
   - renamed project check with `-SkipPythonTests`.

## Acceptance Criteria

- Existing data save path still works.
- `quant_signal_scores` rows include `formula_version=quant_signal_score_v2`.
- A market crash/circuit session produces `AVOID_MARKET_RISK` and final score capped at 25.
- UI can explain score composition without parsing GPT text.
- GPT remains low-weight and cannot override hard market-risk states.
