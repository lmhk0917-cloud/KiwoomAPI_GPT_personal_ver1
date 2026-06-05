# Optimization Review 2026-05-30

다른 Codex 채팅에서 구조 정리와 최적화 결과를 바로 확인할 수 있도록 작성한 인수인계 문서.

## 결론

2026-05-29 구조 정리와 신호 품질 튜닝은 오프라인 기준으로 정상 동작한다.

다음 정규장 테스트에서는 추가 기능 구현보다 아래 흐름을 우선 검증한다.

```text
Kiwoom 로그인
-> 실시간 틱 수신
-> SQLite 저장
-> 이벤트/validation signal 생성
-> GPT 호출
-> Telegram 필터 알림
-> paper-trade 사후 평가
```

구조 변경 이후 실제 정규장 검증은 아직 진행하지 않았다.

## 프로젝트 경로

```text
C:\Users\lmhk2\PycharmProjects\KiwoomAPI_GPT_personal_ver1
```

운영 DB:

```text
C:\Users\lmhk2\PycharmProjects\KiwoomAPI_GPT_personal_ver1\data\ticks.db
```

Python 환경:

```text
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32
```

## 구조 정리 결과

기존 루트 스크립트 명령은 깨지지 않도록 compatibility wrapper로 유지했다.

실제 구현 분리:

```text
reports/
renderers/
tools/
diagnostics/
storage/
ui/
```

주요 구조:

- `reports/`: 일별 테스트, GPT 호출, 시장 컨텍스트, 백필 품질 리포트
- `renderers/`: UI/DB preview 이미지 생성
- `tools/`: 외부 컨텍스트 import, Telegram 테스트, TR 정의 확인 등
- `diagnostics/`: smoke test, login 진단, simulation, stability check
- `storage/schema.py`: SQLite 테이블 생성, additive migration, index
- `ui/labels.py`, `ui/widgets.py`: UI 라벨과 재사용 위젯
- `signal_quality.py`: paper-trade 결과 기반 신호 품질 보정

구조 계획 원문:

```text
PROJECT_STRUCTURE_PLAN_20260529.md
```

정리 기록:

```text
CLEANUP_20260529.md
CLEANUP_20260529_SECOND.md
```

## 신호 품질 튜닝

2026-05-29 장중 결과에서 확인된 문제:

- `WATCH_SUPPORT`: 37개 평가, 60분 평균 -0.217%, 승률 32.43%, 손절 75.68%
- `000660 WATCH_SUPPORT`: 32개 평가, 60분 평균 -0.302%, 승률 25.0%, 손절 78.13%
- `WATCH_PULLBACK`: 8개 평가, 60분 평균 +0.129%, 승률 87.5%, 손절 100.0%
- `000660 WATCH_MOMENTUM`: 4개 평가, 60분 평균 -0.752%, 승률 25.0%, 손절 100.0%

반영된 변경:

1. 확인 근거가 부족한 `WATCH_SUPPORT`는 `OBSERVE_EVENT`로 강등
2. `CONSECUTIVE_UP_BARS` 단독 `WATCH_MOMENTUM`은 `OBSERVE_EVENT`로 강등
3. SK하이닉스 `000660`의 support/momentum 신호에 추가 감점
4. `WATCH_PULLBACK`의 stop anchor는 지나치게 가까우면 현재가 대비 -1%까지 완화

관련 파일:

```text
signal_quality.py
signal_generator.py
```

단위 확인 결과:

```text
000660 미확인 WATCH_SUPPORT -> OBSERVE_EVENT, score 43
000660 단독 WATCH_MOMENTUM -> OBSERVE_EVENT, score 43
pullback stop anchor: 현재가 100, 기존 99.7 -> 99.0
```

## GPT 상태

누적 GPT 호출 기록:

```text
calls=500
success=500
failed=0
total_tokens=4,432,747
```

최근 저장 데이터 재호출도 성공했다.

- model: `gpt-4o-mini-2024-07-18`
- 최근 테스트 종목: 삼성전자 `005930`
- 결과: `대기`
- 뉴스/공시/대중반응 가중치: 실시간 공식에서 1%

GPT 공식 방향:

```text
BreakoutScore =
  min(100,
    30*BoxBreak
  + 25*VolumeSpike
  + 20*VWAPRecover
  + 15*OrderbookBias
  + 10*VolatilityExpand)

TrendScore =
  min(100,
    25*TF_1m
  + 25*TF_3m
  + 25*TF_5m
  + 15*MAAlign
  + 10*StrengthPersist)

CombinedScore =
    0.40*BreakoutScore
  + 0.35*TrendScore
  + 0.15*VolumeTradeScore
  + 0.09*FlowDerivScore
  + 0.01*TextRiskScore
  - RiskPenalty
  - CostPenalty
```

## 이번 검토에서 추가 보강한 부분

### 1. Preflight fail-closed

파일:

```text
preflight_check.py
```

문제:

- CIM/tasklist 프로세스 조회가 모두 실패해도 residual count가 0이면 `PREFLIGHT_STATUS=ok`로 통과할 수 있었다.
- 중복 Kiwoom/OpenAPI 로그인 방지 목적과 맞지 않았다.

수정:

- 프로세스 목록 조회 자체가 실패하면 `PREFLIGHT_STATUS=blocked` 처리
- 실제 로컬 권한에서 CIM 조회가 가능하면 정상적으로 `ok`

검증:

```text
제한 환경: PREFLIGHT_STATUS=blocked, PREFLIGHT_SOURCE=none
실제 로컬 권한: PREFLIGHT_STATUS=ok, PREFLIGHT_SOURCE=cim
```

### 2. SQLite 중복 제거 쓰기 최소화

파일:

```text
storage/schema.py
```

문제:

- `TickStore`를 열 때마다 `historical_bars` 중복 제거 `DELETE`가 실행됐다.
- 읽기용 리포트도 불필요한 DB 쓰기 잠금을 요구했다.

수정:

- 중복 행이 실제로 존재하는지 먼저 조회
- 중복이 있을 때만 `DELETE`

검증:

- 제한 환경에서도 `paper_trade_report.py` 읽기 리포트 실행 성공

## 검증 완료 항목

### Python AST 검사

```text
AST_FILES=79
AST_OK
```

### 리포트 wrapper

```text
today_test_report.py --date 2026-05-29
paper_trade_report.py --min-sample 3 --recent-limit 1
gpt_call_report.py --limit 3
```

모두 정상.

### UI 렌더

```text
render_current_ui_screenshots.py
```

정상 생성:

```text
exports/screenshots/ui_current_overview.png
exports/screenshots/ui_current_chart.png
exports/screenshots/ui_current_operations.png
exports/screenshots/ui_current_market_context.png
exports/screenshots/ui_current_watchlist.png
```

### 오프라인 안정성

```text
stability_check.py --count 180 --cycle-ticks 30
```

결과:

```text
STABILITY_CHECK_RESULT=PASS
```

### 작업 스케줄러 명령 구성

```text
run_market_day_integration.ps1 -ValidateOnly
```

정상.

### OpenAPI 자동 사전 실행

의도대로 비활성 상태:

```text
OPENAPI_BOOTSTRAP_DISABLED=True
```

## 현재 생성된 테스트 산출물

오프라인 검증과 UI 렌더로 아래 파일이 다시 생성됐다.

```text
data/stability_check_simulation.db
data/ui_current_example.db
exports/screenshots/ui_current_*.png
```

운영에 필요하지 않은 테스트 산출물이므로 다음 정리 때 archive 이동 가능.

운영 DB는 이동하거나 삭제하면 안 된다.

```text
data/ticks.db
```

## 다음 정규장 테스트 체크리스트

1. 장 시작 전 사용자가 Kiwoom/OpenAPI 확인창 처리
2. `openapi_bootstrap.disabled` 유지
3. 08:55 작업 스케줄러 실행 확인
4. 09:00 이후 종목별 tick 증가 확인
5. `gpt_call_logs` success 증가 확인
6. Telegram 메시지가 고우선순위 이벤트만 보내는지 확인
7. 새 튜닝 이후 `WATCH_SUPPORT -> OBSERVE_EVENT` 강등 수 확인
8. `WATCH_PULLBACK` 손절 터치율 개선 여부 확인
9. SK하이닉스 support/momentum 신호 수와 평균 수익률 확인
10. 장마감 후 `today_test_report.py`, `paper_trade_report.py` 실행

## 다음 채팅에서 우선할 일

- 다음 정규장 결과가 나오기 전까지 신호 규칙을 추가로 크게 바꾸지 않는다.
- 뉴스 워처는 다음 기능 후보지만, 진입 신호가 아니라 변동성/추격주의 태그로 설계한다.
- 장마감 후 뉴스/공시/대중반응과 paper-trade 결과를 묶어 피드백하는 구조를 우선한다.
- 실시간 뉴스 가중치는 계속 1% 이하로 유지한다.

