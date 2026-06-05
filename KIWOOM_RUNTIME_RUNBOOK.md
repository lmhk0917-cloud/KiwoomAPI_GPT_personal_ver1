# Kiwoom Runtime Runbook

이 프로젝트는 Kiwoom OpenAPI+의 운영 특성상 **한 번에 하나의 로그인/COM 세션**을 기준으로 테스트한다. Kiwoom API 서버는 짧은 시간 안의 중복 로그인이나 연속 `CommConnect()` 호출에 취약할 수 있으므로, smoke test와 main 통합 테스트를 같은 세션에서 연속 실행하지 않는다.

## 원칙

- 장중 통합 테스트가 목표이면 `kiwoom_smoke_test.py`를 먼저 실행하지 않는다.
- 재부팅 직후 또는 Kiwoom/OpenAPI 완전 종료 직후에는 `main_timed_test.py`를 첫 Kiwoom 접속으로 실행한다.
- `kiwoom_smoke_test.py`는 OCX/로그인/실시간 이벤트만 분리 확인할 때 사용한다.
- smoke test를 실행한 뒤 main 통합 테스트를 하려면 Kiwoom/OpenAPI 관련 창과 Python 프로세스를 완전히 종료하거나 PC를 재부팅한다.
- 수동으로 Kiwoom API에 접속한 상태에서는 새 Python 프로세스가 다시 `CommConnect()`를 호출하면 중복 로그인 제한에 걸릴 수 있다.

## 장중 통합 테스트 권장 순서

1. PC 절전 모드를 끈다.
2. 필요한 경우 Kiwoom 자동로그인을 켜둔다.
3. 실행 전 preflight로 Kiwoom/OpenAPI/Python 잔여 세션을 확인한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python main_timed_test.py --preflight-only
```

4. 잔여 세션이 없으면 아래 명령을 첫 Kiwoom 접속으로 실행한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python main_timed_test.py --seconds 60
```

5. 로그와 DB 증가량을 확인한다.

```powershell
Get-Content -Encoding UTF8 logs\main_timed_test_YYYYMMDD.log
```

## Windows 작업 스케줄러 자동 실행

현재 등록된 작업 이름:

```powershell
KiwoomGPTPersonalMarketDayIntegration
```

OpenAPI 사전 실행 작업 이름:

```powershell
KiwoomOpenAPIBootstrap
```

현재 운영 방침:

- OpenAPI 사전 실행 자동화는 비활성화한다.
- `openapi_bootstrap.disabled` 파일이 있으면 `start_kiwoom_openapi.ps1`은 즉시 종료한다.
- 당분간은 오늘처럼 사용자가 장 시작 전 OpenAPI 실행/확인을 수동으로 처리하고, 08:55 장중 통합 테스트만 자동 실행한다.
- 사용자가 08:55에 기상하는 경우, OpenAPI 확인창을 즉시 처리한다. 가능하면 08:50 전후에 처리하는 쪽이 더 안전하다.

동작:

- 평일 08:45에 `start_kiwoom_openapi.ps1`이 `C:\OpenAPI\opstarter.exe`를 실행
- 평일 08:55에 `run_market_day_integration.ps1` 실행
- 09:00 전이면 장 시작까지 대기
- 실행 시점부터 15:31까지 `main_timed_test.py` 실행
- GPT 호출, DB 저장, Telegram 알림, paper report 포함
- 중복 실행은 `IgnoreNew`와 lock 파일로 차단
- 로그는 `logs\market_day_integration_YYYYMMDD_HHMMSS.ps1.log`와 `logs\main_timed_test_YYYYMMDD.log`에 저장

등록/갱신:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\register_openapi_bootstrap_task.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\register_market_day_task.ps1 -OpenApiTaskName KiwoomOpenAPIBootstrap
```

관리자 권한 등록 보조 파일:

```powershell
.\install_openapi_bootstrap_admin.bat
.\install_market_day_task_with_openapi.bat
```

등록 확인:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_openapi_bootstrap_task.ps1
```

주의:

- `KiwoomOpenAPIBootstrap`은 `RunLevel Highest`로 등록한다.
- 이 작업 등록은 관리자 PowerShell에서 한 번 실행해야 한다.
- 등록이 끝나면 다음 장중 자동 실행부터 UAC 확인 버튼을 매번 누르는 상황을 줄일 수 있다.
- Kiwoom/OpenAPI 업데이트가 새로 뜨면 업데이트/보안 프로그램이 별도 확인창을 요구할 수 있다. 이 경우 최초 1회는 수동 처리가 필요할 수 있다.
- 지금은 테스트 우선이므로 `openapi_bootstrap.disabled`를 유지한다. 이 파일을 삭제하면 OpenAPI 사전 실행 자동화가 다시 활성화된다.

관리자 예약 작업 등록이 막히는 경우 현재 사용자 계정에만 `RUNASINVOKER`
호환성 플래그를 적용해 OpenAPI starter의 UAC 확인을 줄일 수 있다.
OpenAPI 업데이트는 수동으로 먼저 완료한 뒤 장중 자동 실행에만 사용한다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\enable_openapi_runas_invoker.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\enable_openapi_runas_invoker.ps1 -ValidateOnly
```

되돌리기:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\enable_openapi_runas_invoker.ps1 -Disable
```

기존 방식으로 통합 테스트 작업만 등록:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\register_market_day_task.ps1
```

등록 해제:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\register_openapi_bootstrap_task.ps1 -Unregister
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\register_market_day_task.ps1 -Unregister
```

실제 실행 없이 명령 구성만 검증:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_kiwoom_openapi.ps1 -ValidateOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_market_day_integration.ps1 -ValidateOnly -OpenApiTaskName KiwoomOpenAPIBootstrap
```

수동으로 OpenAPI 접속을 먼저 해둔 상태만 사용하려면 아래처럼 등록한다. 이 모드에서는 `CommConnect()`를 새로 호출하지 않는다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\register_market_day_task.ps1 -RequireExistingLogin
```

## 거시경제 컨텍스트

장중 앱은 로그인 이후 `macro_context_fetcher.py`를 주기적으로 실행해 GPT 입력용 `macro_context`를 갱신한다.

현재 자동 수집:

- 한국은행 기준금리
- 미국 연방기금 목표금리 범위
- 한국은행 통화정책방향 결정회의 일정

수동 확인:

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python macro_context_fetcher.py --json
```

주의:

- 크롤링 실패는 장중 앱을 중단하지 않고 `macro_context.notes`에 기록한다.
- 원/달러 환율은 `fx_usd_krw` TR 매핑 후보를 추가했지만, 로컬 OpenAPI 파일에서 검증된 OPT/OPW TR 코드를 확인하지 못해 기본값은 비활성화 상태다.
- KOA Studio에서 정확한 환율 TR 코드, 입력명, 출력명을 확인한 뒤 `kiwoom_context_mappings.py`의 `fx_usd_krw`를 활성화한다.

## 장마감 GPT 피드백

실시간 GPT 공식에서는 뉴스/공시/대중반응 가중치를 1% 이하로 유지한다.
뉴스 크롤링 또는 수동 뉴스 요약은 장중 판단보다 장마감 피드백에서 사용한다.

장마감 후 뉴스/공시/대중반응 JSON을 준비했다면 먼저 import한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python external_context_import.py --file external_context.example.json --merge-market-context-json
```

그 다음 사후 성과와 뉴스 컨텍스트를 함께 GPT에 전달한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python post_market_feedback_gpt.py --days 1 --min-sample 5
```

결과는 `exports\post_market_feedback_YYYYMMDD_HHMMSS.md`에 저장된다.

## 잔여 세션 정리 옵션

기본값은 안전하게 차단만 한다. 잔여 세션을 자동 종료하려면 명시적으로 `--kill-residual`을 붙인다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python main_timed_test.py --preflight-only --kill-residual
```

주의:

- 알 수 없는 다른 `python.exe`는 자동 종료하지 않고 보고만 한다.
- 현재 프로젝트 스크립트로 판단되는 Python 프로세스와 Kiwoom/OpenAPI 관련 프로세스만 종료 대상이 된다.
- 수동으로 Kiwoom에 접속해둔 상태에서 통합 테스트를 실행하려면 중복 로그인 제한 때문에 실패할 수 있다.

## 이전 수동 확인 방식

아래 수동 확인은 필요할 때만 사용한다.

```powershell
Get-Process | Where-Object { $_.ProcessName -like 'python*' } | Select-Object Id,ProcessName,StartTime,CPU
```

## 기존 직접 실행 명령

preflight를 건너뛰려면 `--skip-preflight`를 붙일 수 있지만, 장중 통합 테스트에서는 권장하지 않는다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python main_timed_test.py --seconds 60 --skip-preflight
```

## 분리 smoke test

OCX 생성, 로그인, 실시간 이벤트만 확인할 때 사용한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_smoke_test.py --login-timeout-sec 30 --realtime-seconds 10
```

이 테스트가 성공해도 바로 이어서 main 통합 테스트를 실행하지 않는다. Kiwoom 중복 로그인 제한 때문에 두 번째 프로세스가 로그인 이벤트를 받지 못할 수 있다.

## 최소 실시간 수집기

`main.py` 통합 앱이 로그인 단계에서 불안정하면, GPT/Telegram/분석을 전부 제외한 최소 collector로 먼저 DB 저장만 검증한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_realtime_collector.py --seconds 60 --login-timeout-sec 45
```

성공 기준:

- `COLLECTOR_LOGIN_RESULT=0`
- `COLLECTOR_REALTIME_REGISTER_RESULT=0`
- `COLLECTOR_SAVED_TICK_COUNT`가 1 이상
- `COLLECTOR_DB_DELTA=ticks:`가 1 이상

실패 예:

- `COLLECTOR_LOGIN_TIMEOUT=True`: `CommConnect()` 호출 후 로그인 이벤트가 오지 않음. Kiwoom 로그인창, 자동로그인, 중복 로그인 상태를 직접 확인해야 한다.
- `COLLECTOR_ABORTED=existing_login_not_confirmed`: `--require-existing-login` 모드에서 Python OpenAPI 컨트롤이 기존 수동 접속을 연결로 인식하지 못함.

## 현재 코드 반영 사항

- `KiwoomClient.login()`은 `GetConnectState()`가 이미 연결 상태이면 `CommConnect()`를 생략한다.
- `kiwoom_smoke_test.py`도 이미 연결된 상태면 로그인 요청을 생략한다.
- `main_timed_test.py`는 로그인 미완료 상태에서 종료할 때 실시간 해제 COM 호출을 생략한다.
- `main_timed_test.py`는 시작 전에 preflight를 실행해 잔여 Python/Kiwoom 세션이 있으면 기본적으로 중단한다.
- `kiwoom_realtime_collector.py`는 Kiwoom 로그인과 tick SQLite 저장만 수행하는 최소 수집기다.
- smoke test 종료 시 실시간 등록 해제를 시도한다.

## Kiwoom/OpenAPI 업데이트 이후 로그인 실패

`QAxWidget` 생성은 성공하지만 `CommConnect()` 이후 로그인 이벤트가 오지 않고
`C:\OpenAPI\log` 파일이 갱신되지 않으면 앱 내부 분석 로직 문제가 아니라 OpenAPI 런타임
로그인 단계 문제로 본다.

이 경우 아래 순서로 처리한다.

1. KOA Studio, 영웅문, OpenAPI 로그인 창, 이전 Python 프로세스를 모두 종료한다.
2. `preflight_check.py`로 잔여 세션이 없는지 확인한다.
3. `kiwoom_login_diagnostics.py`를 실행해 OpenAPI 파일, COM 등록, 최근 로그를 저장한다.
4. KOA Studio 또는 OpenAPI 로그인 창을 수동 실행해 업데이트를 끝까지 완료한다.
5. 모든 Kiwoom 관련 창을 닫고 다시 `kiwoom_realtime_collector.py`를 실행한다.
6. 그래도 실패하면 관리자 PowerShell에서 32-bit OCX 재등록을 검토한다.

```powershell
C:\Windows\SysWOW64\regsvr32.exe C:\OpenAPI\khopenapi.ocx
```

자세한 절차는 `KIWOOM_LOGIN_TROUBLESHOOTING.md`를 따른다.
