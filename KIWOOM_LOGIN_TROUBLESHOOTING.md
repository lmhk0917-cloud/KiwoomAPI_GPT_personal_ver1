# Kiwoom Login Troubleshooting

이 문서는 Kiwoom OpenAPI+ 로그인 단계에서 `QAxWidget`은 생성되지만
`CommConnect()` 이후 로그인 이벤트가 오지 않는 상황을 점검하기 위한 절차다.

## 현재 관찰된 상태

- `QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")` 생성은 성공했다.
- Python OpenAPI 컨트롤의 `GetConnectState()`는 `0`으로 유지됐다.
- 수동으로 Kiwoom/KOA에 로그인해도 Python OpenAPI 컨트롤에는 기존 연결로 보이지 않았다.
- `kiwoom_realtime_collector.py` 실행 시 `COLLECTOR_LOGIN_TIMEOUT=True`가 발생했다.
- 실패 시점의 `C:\OpenAPI\log` 파일이 갱신되지 않았다.
- `C:\OpenAPI\system\MultiLogin.ini`에 `use=1`이 설정되어 있어 중복 로그인 제한이 활성화된 상태다.
- `C:\OpenAPI\system\opcomms.ini` 기준 현재 서버 설정은 `SERVERTYPE=1`, `USE_APIVTS=0`이다.

## 판단

현재 증상은 DB, GPT, Telegram, UI 문제가 아니라 Kiwoom OpenAPI+ 런타임 로그인 단계 문제로 보는 것이 맞다.
특히 OCX 생성은 되는데 OpenAPI 로그가 갱신되지 않는다면 앱 내부 분석 로직까지 도달하지 못한 것이다.

가능성이 높은 원인은 다음 순서다.

1. KOA Studio, 영웅문, OpenAPI 로그인 창, 이전 Python 프로세스 중 하나가 세션을 점유한다.
2. 최근 OpenAPI 업데이트 이후 파일/등록 상태가 반쯤 갱신되어 `CommConnect()`가 정상 스타터까지 도달하지 못한다.
3. 자동로그인 파일은 존재하지만 현재 Python OpenAPI 컨트롤이 해당 세션을 인식하지 못한다.
4. 32-bit OCX 등록은 되어 있으나 업데이트 후 재등록이 필요하다.

## 빠른 점검 순서

1. KOA Studio와 영웅문 관련 창을 모두 종료한다.
2. 프로젝트에서 잔여 세션을 확인한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python preflight_check.py
```

3. `PREFLIGHT_STATUS=ok`가 아니면 수동 종료 후 다시 확인한다.
4. 읽기 전용 진단을 실행한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_login_diagnostics.py
```

5. 최소 collector로 로그인만 확인한다.

```powershell
C:\Users\lmhk2\anaconda3\Scripts\conda.exe run --no-capture-output -n py37_32 python kiwoom_realtime_collector.py --seconds 30 --login-timeout-sec 45
```

성공 기준은 다음과 같다.

- `COLLECTOR_LOGIN_RESULT=0`
- `COLLECTOR_REALTIME_REGISTER_RESULT=0`
- 장중이면 `COLLECTOR_SAVED_TICK_COUNT`가 1 이상

## 업데이트 이후 복구 절차

아래 절차는 관리자 권한 또는 수동 GUI 조작이 필요할 수 있다.

1. PC를 재부팅한다.
2. KOA Studio 또는 OpenAPI 로그인 창을 한 번 수동 실행해 업데이트를 끝까지 완료한다.
3. 업데이트/로그인 관련 팝업이 있으면 모두 완료한다.
4. KOA Studio와 영웅문을 완전히 종료한다.
5. 프로젝트에서 `preflight_check.py`가 `ok`인지 확인한다.
6. 그래도 `CommConnect()`가 로그를 갱신하지 못하면 32-bit OCX 재등록을 검토한다.

관리자 PowerShell에서 실행할 명령:

```powershell
C:\Windows\SysWOW64\regsvr32.exe C:\OpenAPI\khopenapi.ocx
```

재등록 후에는 PC를 재부팅하고, 다시 `preflight_check.py`와
`kiwoom_realtime_collector.py` 순서로 확인한다.

## 주의

- 수동 Kiwoom 로그인은 Python `QAxWidget` 연결 성공과 동일하지 않다.
- 중복 로그인 제한 때문에 smoke test와 main test를 연속 실행하면 두 번째 실행이 실패할 수 있다.
- 정규장 수집 목적이면 `main.py`보다 `kiwoom_realtime_collector.py`를 먼저 성공시키는 것이 우선이다.
- 이 개인 프로젝트에는 매수/매도 호출을 넣지 않는다.
