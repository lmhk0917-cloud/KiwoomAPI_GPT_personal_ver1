# Kiwoom Core Quant Lab

Legacy folder: `C:\Users\lmhk2\PycharmProjects\Kiwoom_Core_Quant_Lab`

## Current Direction

This project is now the focused-symbol, traditional-quant investment project.
It should not be expanded into broad realtime screening unless the user
explicitly reverses this decision.

## Primary Goal

Build a reliable Kiwoom-based quant lab for a small core watchlist, especially
Samsung Electronics and SK hynix. The project should collect and preserve
market data, compute deterministic indicators and factor-style scores, validate
signals with backtests or paper-trade evidence, and make risk/reward decisions
auditable.

## Scope

- Deep analysis of selected core symbols.
- Traditional quant workflow: factors, signal score, beta, correlation, hit
  ratio, drawdown, upside/downside, position sizing, and post-session feedback.
- Kiwoom OpenAPI+ realtime ticks, historical bars, SQLite persistence, and
  conservative market-hour operation.
- GPT is a reviewer and report assistant, not a trade executor.

## Non-Goals

- Do not turn this project into a broad market screener.
- Do not make GPT the primary decision engine.
- Do not add automatic live trading.
- Do not remove Kiwoom/OpenAPI preflight safeguards.

## Collaboration Notes

- Treat this repository as the source of truth for the personal quant workflow.
- Prefer deterministic logic and measurable validation before GPT wording.
- Keep runtime entrypoints stable.
- Respect existing uncommitted changes; do not revert user work.
- Use offline/unit tests first. Do not run live Kiwoom login probes unless the
  user explicitly asks during market-prep work.
