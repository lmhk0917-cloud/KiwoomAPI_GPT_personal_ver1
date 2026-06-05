# Kiwoom GPT Personal Market Analysis System

Kiwoom OpenAPI+ realtime market data and OpenAI GPT analysis are connected into a personal Korean stock-market analysis system. The project focuses on collecting live ticks, converting them into multi-timeframe indicators, detecting meaningful events, calling GPT only when needed, and storing every result for review and paper-trade feedback.

This is not an automated trading bot. The current goal is risk/reward analysis, signal review, data collection, and validation.

## Project Goals

- Build a working realtime data pipeline under the constraints of Kiwoom OpenAPI+ and 32-bit Python.
- Store raw ticks, generated events, GPT calls, notifications, and paper-trade evaluations in SQLite.
- Analyze selected high-interest symbols deeply rather than screen the whole market broadly.
- Use GPT as a reasoning and review layer, while deterministic code handles data collection, indicator calculation, event detection, and logging.
- Improve signal quality through repeated market-session tests and paper-trade feedback.

## Technical Context

- OS: Windows
- Runtime: Anaconda 32-bit Python 3.7
- Broker API: Kiwoom OpenAPI+
- GUI/Event bridge: PyQt5 + QAxWidget
- Database: SQLite
- AI API: OpenAI chat completions
- Tested model: `gpt-4o-mini`
- Notification: Telegram

Kiwoom OpenAPI+ requires a Windows desktop session and COM/QAxWidget integration. Because of that, this project is intentionally local-first and designed around supervised market-hour runs.

## Core Features

- Realtime Kiwoom tick collection
- SQLite persistence for:
  - ticks
  - analysis results
  - event logs
  - GPT call logs
  - notification logs
  - signal logs
  - paper-trade results
  - historical bars
  - market context snapshots
- 1m / 3m / 5m OHLCV conversion
- Technical indicators:
  - MA5 / MA20 / MA60
  - MA distance from current price
  - VWAP and VWAP distance
  - RSI
  - MACD
  - ATR
  - Bollinger Band
  - volume ratios
  - box-range position
- Event-driven GPT calls
- GPT input compression
- Cost-aware analysis using fee, tax, and slippage assumptions
- Telegram alert filtering
- Paper-trade evaluation loop
- PyQt dashboard for monitoring DB, signals, GPT logs, settings, and charts
- Market context hooks for investor flow, program trading, derivatives, macro data, news, disclosures, and public reaction
- Runbooks and diagnostics for Kiwoom login/session stability

## Data Flow

```text
Kiwoom realtime ticks
-> TickStore memory buffer and SQLite
-> 1m / 3m / 5m bars
-> indicators and market snapshots
-> event detection
-> validation signal generation
-> GPT payload compression
-> OpenAI chat completion
-> DB logging
-> Telegram / console notification
-> paper-trade evaluation
-> feedback into future analysis
```

## GPT Input Design

GPT does not receive the full raw DB. The system compresses the current analysis state into a focused JSON payload.

Included examples:

- Current price, volume, intraday open/high/low, strength
- 1m / 3m / 5m indicator summaries
- VWAP distance percentage
- MA5 / MA20 / MA60 distance percentages
- RSI, MACD, ATR, Bollinger, volume ratios
- Detected events
- Local validation signal and risk level
- Market ETF context such as KODEX 200 and KODEX KOSDAQ150
- Foreign/institution/program flow when available
- Derivatives and macro context when available
- Short selling and credit context when available
- Historical daily/minute bar summaries
- Paper-trade performance feedback
- Fee, tax, and slippage assumptions

This design keeps token usage controlled while preserving the quantitative evidence needed for short-term risk/reward judgment.

## Current Scope

The current project intentionally focuses on a small set of selected symbols, mainly Samsung Electronics and SK Hynix, with market benchmark ETFs used as context. This is a deliberate design choice: the priority is deeper understanding of selected names and market regime behavior, not broad realtime screening.

## Current Limitations and Improvement Plan

The project is already operational, but it is still an evolving research system. The most important part of the work now is not adding more indicators blindly, but improving reliability, data quality, validation logic, and operating discipline.

### 1. Kiwoom Runtime Dependency

Current limitation:

- Kiwoom OpenAPI+ requires a Windows desktop environment, GUI login state, and QAxWidget.
- Live testing depends on market hours and the stability of the local session.
- Native Qt/Kiwoom crashes can happen outside normal Python exception handling.

Improvement plan:

- Keep strengthening supervisor scripts and restart logic.
- Separate data collection, analysis, and reporting more clearly.
- Maintain preflight checks for residual sessions, login state, DB health, and recent tick growth.
- Preserve offline simulation tests so code quality can be checked even outside market hours.

This is a realistic systems constraint, and the project already reflects the ability to work with awkward external APIs instead of assuming an ideal cloud-only environment.

### 2. Signal Quality and Market Regime Awareness

Current limitation:

- Early rebound signals are still weaker than confirmed pullback or trend-continuation signals.
- A falling market can produce many technically tempting but low-quality rebound candidates.
- Some event types need more evaluated samples before thresholds can be trusted.

Improvement plan:

- Treat `WATCH_PULLBACK` as the primary high-quality long setup until rebound signals prove themselves.
- Require stronger confirmation for `WATCH_REBOUND`, especially:
  - index ETF 3m/5m recovery
  - VWAP reclaim
  - reduced foreign/program selling
  - volume expansion
  - orderbook confirmation
- Use paper-trade results to adjust confidence scores and thresholds.
- Track performance by action type, symbol, time window, and market regime.

The intent is to avoid overfitting one indicator and build a feedback loop that makes each market session more informative.

### 3. GPT Role Definition

Current limitation:

- GPT is good at integrating evidence, but it should not be the sole source of truth.
- If too much raw data is sent, token cost, latency, and noise increase.
- If too little context is sent, GPT may miss market-regime risk.

Improvement plan:

- Keep deterministic code responsible for raw calculations, event detection, and validation.
- Use GPT as a reviewer that explains risk/reward, conflicting evidence, and missing data.
- Improve payload compression so GPT gets more useful quantitative context without receiving raw noise.
- Add structured outputs later so GPT responses can be scored and compared more easily.

This project treats LLMs as one layer in a larger decision system, not as a magic trading oracle.

### 4. Historical Data and Backtesting

Current limitation:

- Realtime data is accumulating, but robust strategy evaluation needs more labeled history.
- Current paper-trade evaluation is useful but still sample-size limited.
- Raw ticks are valuable but expensive to keep forever without an archive policy.

Improvement plan:

- Continue collecting live data for representative market regimes.
- Backfill daily/minute bars where Kiwoom TR limits allow.
- Evaluate signals over 5m, 10m, 30m, and 60m horizons.
- Compare action types across different market conditions.
- Later, convert the data into training/evaluation datasets for model comparison.

The longer-term direction is a measured research pipeline: collect, label, evaluate, adjust, and only then automate more.

### 5. UI and Productization

Current limitation:

- The dashboard exists, but it is still primarily an engineering/debugging tool.
- Configuration editing and visual review can be improved.
- Packaging into an executable is not yet the main priority because live data stability matters first.

Improvement plan:

- Improve the dashboard around the actual workflow:
  - watchlist editing
  - threshold editing
  - signal review
  - GPT call history
  - paper-trade performance
  - chart and indicator visualization
- Package the app only after the live-session workflow is stable.
- Keep sensitive credentials outside the repository and runtime logs.

This shows the intended path from prototype to usable personal application without hiding current rough edges.

### 6. Future Advanced Direction

Current limitation:

- GPT currently receives compressed summaries, not the full raw historical dataset.
- Full raw-data reasoning would require more storage, retrieval, and modeling infrastructure.

Improvement plan:

- Store raw data locally and summarize it for current GPT calls.
- Later introduce retrieval over raw historical patterns.
- Compare current setups with similar past setups.
- Add dedicated statistical or ML models for short-horizon risk prediction.
- Keep GPT as an explanation and synthesis layer above deterministic/quantitative models.

The long-term architecture is not "send everything to GPT." It is "build a data system where GPT can inspect the right evidence at the right time."

## Security Notes

The repository intentionally excludes local secrets and runtime data:

- `.env`
- SQLite databases
- logs
- exports
- local market context state
- IDE files
- Python cache
- archive data

Use `.env.example` as a template and create a local `.env` file for actual credentials.

## Typical Local Workflow

```powershell
# Run offline stability checks
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python stability_check.py --count 180 --cycle-ticks 30

# Run GPT smoke test
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python gpt_smoke_test.py

# Inspect GPT call history
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python gpt_call_report.py --limit 5
```

Live Kiwoom tests require the correct Windows desktop session, Kiwoom OpenAPI+ installation, login state, and market-hour availability.

## Portfolio Note

This project is valuable less because it "predicts stocks" and more because it demonstrates work across a difficult integration boundary:

- legacy Windows COM API
- realtime event-driven data collection
- SQLite schema design
- market-data feature engineering
- LLM prompt/payload design
- logging and observability
- alerting
- paper-trade validation
- UI monitoring
- operational runbooks

The current limitation list is intentional. It documents the next engineering problems clearly and shows the direction for solving them.

---

# 키움 GPT 개인용 시장 분석 시스템

이 프로젝트는 키움 OpenAPI+의 실시간 주식 데이터를 수집하고, OpenAI GPT 분석을 연결해 만든 개인용 한국 주식시장 분석 시스템입니다. 핵심 목표는 자동매매가 아니라, 실시간 데이터를 저장하고 지표로 변환한 뒤 이벤트가 발생했을 때 수익 대비 위험을 판단하고, 그 결과를 다시 모의 검증 데이터로 축적하는 것입니다.

현재는 삼성전자, SK하이닉스처럼 관심도가 높은 소수 종목을 깊게 분석하는 방향으로 설계했습니다. 무작정 많은 종목을 스크리닝하기보다, 실시간 틱, 분봉, 수급, 시장 ETF, 거시 맥락, GPT 판단 근거, 사후 성과를 함께 쌓아가며 단기 판단 품질을 개선하는 데 초점을 두고 있습니다.

## 한국어 요약

- 키움 OpenAPI+ 실시간 체결 데이터 수집
- SQLite 기반 틱/이벤트/GPT 호출/알림/모의검증 로그 저장
- 1분/3분/5분봉 변환
- MA, VWAP, RSI, MACD, ATR, Bollinger Band, 거래량 배율, 박스권 위치 계산
- 이벤트 기반 GPT 호출
- GPT 입력 압축 및 토큰 사용량 기록
- 수수료, 세금, 슬리피지 반영
- Telegram 알림
- PyQt 기반 대시보드
- paper-trade 방식의 사후 성과 평가
- 장중 테스트, 로그인 문제, OpenAPI 제약에 대한 runbook과 진단 스크립트 포함

## 현재 신분과 프로젝트 배경

저는 현재 대학교 2학년으로, 아직 실무 환경이나 대규모 인프라, 전문적인 금융 데이터 접근 권한, 팀 단위 리뷰 프로세스를 충분히 경험하기 어려운 제약이 있습니다. 그래서 이 프로젝트는 제한된 개인 환경에서 직접 부딪히며 만든 실전형 학습 프로젝트입니다.

특히 키움 OpenAPI+는 Windows, 32-bit Python, QAxWidget, GUI 로그인 세션이라는 제약이 강합니다. 그 안에서 실시간 데이터 수집, 장애 대응, 저장 구조, GPT 연동, 알림, UI, 검증 루프까지 직접 구성하면서 단순 예제 코드가 아니라 실제로 동작하는 시스템을 만들고자 했습니다.

제가 현장에 나가고 싶은 이유도 여기에 있습니다. 혼자서 문제를 정의하고 해결하는 과정은 많이 해봤지만, 이제는 실제 개발팀 안에서 코드 리뷰, 운영 기준, 데이터 품질 관리, 모델 검증, 제품화 의사결정이 어떻게 이루어지는지 배우고 싶습니다. 이 프로젝트는 제가 완성된 전문가라고 주장하기 위한 것이 아니라, 복잡한 제약을 끝까지 다루고 개선 계획을 세울 수 있다는 점을 보여주기 위한 작업입니다.

## 현재 한계와 개선 방향

이 프로젝트는 아직 완성품이라기보다 계속 데이터 수집과 검증을 진행 중인 연구/개발 시스템입니다. 현재 한계를 숨기기보다 명확히 정리하고, 각각을 어떻게 해결할지 계획을 세우는 데 중점을 두고 있습니다.

### 1. 실시간 운영 안정성

현재 한계:

- 키움 OpenAPI+는 Windows GUI 로그인 세션에 의존합니다.
- 정규장 시간에만 실제 틱 수신을 검증할 수 있습니다.
- Qt/Kiwoom 쪽 native crash는 Python 예외 처리만으로 완전히 제어하기 어렵습니다.

개선 계획:

- supervisor와 자동 재시작 로직 강화
- 잔여 세션, 로그인 상태, DB 적재량, 최근 오류를 확인하는 preflight 절차 유지
- 장중 테스트 결과를 계속 누적해 실패 패턴을 분류
- 데이터 수집과 분석 프로세스의 책임 분리

### 2. 신호 품질과 시장 국면 판단

현재 한계:

- 하락장에서 초기 반등 신호는 아직 신뢰도가 낮습니다.
- 단기 지표만으로는 외국인 매도세, 프로그램 매도, 지수 약세를 충분히 반영하기 어렵습니다.
- 종목별/시간대별 샘플 수가 아직 더 필요합니다.

개선 계획:

- `WATCH_PULLBACK`처럼 검증 성과가 좋은 신호를 우선 관찰
- `WATCH_REBOUND`는 지수 ETF 3m/5m 회복, VWAP 회복, 거래량 증가, 외국인/프로그램 매도 완화가 함께 확인될 때만 신뢰도 상향
- action별 승률, 손절률, 30분/60분 수익률을 계속 축적
- 시장 국면별로 임계값을 다르게 적용

### 3. GPT의 역할

현재 한계:

- GPT가 모든 원본 데이터를 직접 읽는 구조는 비용과 지연이 큽니다.
- GPT는 판단 근거를 통합하는 데 강하지만, 지표 계산과 신호 생성까지 전부 맡기는 것은 적절하지 않습니다.

개선 계획:

- 원본 계산, 이벤트 감지, 비용 계산은 deterministic code에서 처리
- GPT는 시장 맥락, 충돌하는 근거, 위험 요인, 확인 조건을 해석하는 reviewer로 사용
- payload 압축을 개선해 토큰 사용량을 통제
- 향후 structured output을 붙여 GPT 판단도 정량 평가 가능하게 개선

### 4. 백테스팅과 데이터셋

현재 한계:

- 충분히 다양한 시장 국면의 데이터가 아직 더 필요합니다.
- 현재는 실시간 수집 데이터와 paper-trade 평가를 쌓아가는 단계입니다.

개선 계획:

- 정규장 데이터를 계속 누적
- 일봉/분봉 backfill 데이터와 실시간 데이터를 결합
- 신호 발생 후 5분/10분/30분/60분 수익률과 최대 손실을 라벨링
- 향후 유사 패턴 검색, 별도 ML 모델, fine-tuning 가능성을 검토

### 5. 패키징과 배포

현재 한계:

- 아직 exe 패키징은 하지 않았습니다.
- 이유는 현재 단계의 우선순위가 실행파일 배포보다 데이터 수집, 장중 안정성 검증, 신호 품질 개선, UI/설정 구조 조정에 있기 때문입니다.
- 패키징을 너무 빨리 하면 테스트와 수정 속도가 느려질 수 있습니다.

개선 계획:

- 장중 데이터 수집과 GPT 호출 흐름이 충분히 안정화된 뒤 패키징 진행
- PyQt UI에서 종목, 임계값, 알림 설정을 더 쉽게 수정하도록 개선
- 패키징 전 로그 경로, 설정 파일, DB 경로, 비밀키 관리 방식을 정리
- 이후 개인용 실행파일 또는 앱 형태로 정리

## 포트폴리오 관점에서 보여주고 싶은 점

이 프로젝트의 목적은 "주가를 맞혔다"를 보여주는 것이 아닙니다. 제가 보여주고 싶은 것은 다음입니다.

- 까다로운 외부 API 제약을 실제로 다뤄본 경험
- 실시간 데이터 파이프라인을 직접 구성한 경험
- DB 스키마와 로그를 설계하고 검증한 경험
- GPT를 무작정 호출하지 않고 이벤트 기반으로 연결한 경험
- 토큰 비용, 입력 압축, 프롬프트 설계를 고민한 흔적
- 알림, UI, 자동 실행, 장중 테스트, 장애 대응까지 이어간 실행력
- 현재 한계를 인식하고 다음 개선 단계를 구체적으로 정리하는 태도

아직 부족한 부분이 많지만, 그래서 더 현장에서 배우고 싶습니다. 실제 팀에서 더 나은 코드 구조, 테스트 전략, 배포 방식, 데이터 검증, 운영 안정성 기준을 배우며 이 프로젝트에서 얻은 문제 해결 경험을 더 높은 수준으로 확장하고 싶습니다.
