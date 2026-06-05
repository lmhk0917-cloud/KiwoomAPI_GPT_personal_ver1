# Intraday Test Report 2026-06-01

## Result

오늘 장중 통합 테스트는 첫 로그인 대기 인스턴스를 정리한 뒤 `09:12:40`에 재시작했고, `15:31:45`에 정상 종료했다.

- scheduler task: `KiwoomGPTPersonalMarketDayIntegration`
- scheduler final state: `Ready`
- launcher exit code: `0`
- DB size: `654.63 MB`
- ticks: `838930`
  - `005930` 삼성전자: `524702`
  - `000660` SK하이닉스: `314228`
- analysis results: `164`
- event logs: `1516`
- GPT calls: `151`
  - success: `151`
  - failed: `0`
  - total tokens: `1090745`
- signal logs: `360`
- notification logs: `207`
  - console: `200`
  - Telegram: `7`
- paper-trade results evaluated today: `7`
  - average 60m return: `1.571%`
  - 60m win rate: `71.43%`
  - stop rate: `28.57%`

오늘 paper-trade 표본은 `7`건이므로 전략 성과를 확정하기에는 부족하다.

## Login Delay

첫 예약 실행은 `09:00:04`에 시작했지만 OpenAPI 로그인 콜백이 오지 않았다.

기존 `main_timed_test.py`는 로그인 확인 시간이 지나도 `LOGIN_CHECK_STATUS=not_logged_in`만 출력하고 장마감까지 빈 인스턴스를 유지했다. 사용자가 모바일 환경에 있으면 자동 복구를 판단하기 어려운 상태였다.

### Applied Fix

`main_timed_test.py`를 수정했다.

- 로그인 확인 제한 시간이 지나면 `TIMED_TEST_ABORTED=login_not_confirmed`를 출력한다.
- DB와 타이머를 정리하고 종료 코드 `11`로 종료한다.
- 내부 OpenAPI 모달 창 때문에 일반 종료가 지연될 경우 5초 뒤 제한된 강제 종료를 수행한다.
- 로그인 창을 반복 호출하는 자동 재시도는 추가하지 않았다. Kiwoom 중복 로그인 위험을 줄이기 위한 결정이다.

## TR Overflow

오늘 OpenAPI 로그에서 `P Overflow [-200]`가 `89`회 관찰됐다.

기존 로직은 한 배치의 TR 요청을 여러 개의 `QTimer.singleShot`으로 동시에 예약했다. GPT 호출 등으로 Qt 이벤트 루프가 잠시 지연되면 이미 만료된 타이머가 연속 실행되어 TR 요청이 몰릴 수 있었다.

### Applied Fix

`main.py`의 시장 컨텍스트 TR 요청을 직렬 큐로 변경했다.

- 요청 하나를 보낸 뒤 설정된 지연 시간이 지난 후 다음 요청을 예약한다.
- 이전 배치가 남아 있으면 새 배치를 시작하지 않는다.
- UI에서 관리하는 기존 TR 간격 설정은 유지한다.

오프라인 큐 검증 결과:

```text
STEP1_CALLS=['first'] TIMERS=1
STEP2_CALLS=['first', 'second'] TIMERS=1
STEP3_CALLS=['first', 'second', 'third'] TIMERS=0
TR_QUEUE_STATUS=ok
```

## Codex Windows Popup

금요일 이후 나타난 경로 팝업은 Kiwoom 또는 프로젝트 오류가 아니다.

팝업은 `C:\Program Files\WindowsApps\OpenAI.Codex...` 경로 뒤에 `wtype=action&action=1&tag=...`가 붙은 Codex Windows 알림 액션 실행 실패다.

확인 결과:

- 현재 Codex package: `OpenAI.Codex_26.527.3686.0_x64__2p2nqsd0c76g0`
- package status: `Ok`
- current executable: `...\app\Codex.exe`
- `codex:` protocol registration: present
- Kiwoom scripts and Windows scheduled tasks: no Codex WindowsApps path reference
- old Codex package directories: removed

기존 Windows 알림 또는 Codex 앱 알림 액션 처리 문제로 분류한다. 프로젝트 코드는 수정하지 않는다.

우선 오래된 Codex 알림을 Windows 알림 센터에서 지운다. 새로 생성된 알림을 눌러도 같은 팝업이 반복되면 Codex 작업을 종료한 뒤 Windows 앱 설정에서 Codex 복구 또는 재설치를 진행한다.

## Verification

- Python AST check: `79` files passed
- offline stability check: passed
- TR serial queue offline check: passed
- launcher validate-only check: passed
- preflight residual session count: `0`

## Next Online Test

다음 정규장 테스트에서 아래 항목을 확인한다.

1. 로그인 콜백이 제한 시간 내에 오지 않으면 첫 인스턴스가 종료 코드 `11`로 정리되는지 확인한다.
2. 정상 로그인 후 틱 적재가 시작되는지 확인한다.
3. `P Overflow [-200]` 발생 횟수가 감소하는지 확인한다.
4. GPT 호출, Telegram 필터, 장마감 종료 코드 `0`을 확인한다.
