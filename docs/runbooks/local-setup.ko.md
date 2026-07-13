# 로컬 실행 초기 세팅 가이드

이 문서는 현재 v2 런타임을 Windows 로컬에서 바로 실행하기 위한 절차입니다.
처음 실행 경로는 `dry-run` 모드입니다.

`dry-run` 모드는 실제 trade lifecycle을 실행하지만 Binance API를 호출하지 않습니다.
진입 주문, TP 주문, SL 주문 의도를 SQLite에 기록만 합니다.

## 1. 사전 요구사항

Python 3.10 이상을 사용해야 합니다.
현재 작업 환경에서 검증된 인터프리터는 다음입니다.

```powershell
C:\Python310\python.exe
```

기본 `python`이 Python 3.9를 가리키면 사용하지 마세요.
현재 코드베이스는 `A | None` 같은 Python 3.10 문법을 사용합니다.

인터프리터와 주요 의존성을 확인합니다.

```powershell
C:\Python310\python.exe --version
C:\Python310\python.exe -c "import fastapi, uvicorn, pytest; print('deps ok')"
```

의존성이 없으면 설치합니다.

```powershell
C:\Python310\python.exe -m pip install -r requirements.txt
```

## 2. 환경 변수 설정

필요하면 샘플 환경 파일을 복사합니다.

```powershell
Copy-Item .env.example .env
```

안전한 로컬 실행은 아래 값을 사용합니다.

```powershell
$env:GPTRADER_MODE='dry-run'
$env:GPTRADER_LIVE_ARMED='false'
$env:GPTRADER_SYMBOL='BTCUSDT'
$env:GPTRADER_TIMEFRAME='1m'
$env:GPTRADER_CANDLE_LIMIT='100'
$env:GPTRADER_CLIENT_ORDER_ID_PREFIX='gptrader-dry-run'
$env:GPTRADER_GENERATOR_ID='dry-run-generator'
$env:GPTRADER_SIGNAL_ID_PREFIX='dry-run-signal'
$env:GPTRADER_DB_URL='sqlite:///./gptrader-dry-run.sqlite3'
```

`local` 또는 `dry-run` 모드에서는 Binance API key가 필요하지 않습니다.

## 3. 테스트 확인

런타임을 실행하기 전에 전체 테스트를 돌립니다.

```powershell
C:\Python310\python.exe -m pytest -q
```

현재 기대 결과:

```text
269 passed
```

## 4. Trade Lifecycle 단발 실행

아래 명령은 trade lifecycle을 한 번 실행합니다.
결과적으로 dry-run entry 주문 1개와 Binance 스타일 보호 주문 2개가 기록됩니다.

- `TAKE_PROFIT_MARKET`
- `STOP_MARKET`

보호 주문은 실제 Binance로 전송되지 않고 SQLite에 기록됩니다.
실제 live/testnet 연결 시에는 Binance에 `closePosition=true`, `stopPrice=<계산된 가격>` 형태로 던지는 구조입니다.

```powershell
C:\Python310\python.exe -c "import os; from src.runtime import RuntimeSettings, create_local_runtime; runtime=create_local_runtime(RuntimeSettings.from_env(os.environ)); result=runtime.run_trade_execution_once('manual-smoke'); print(result.status.value, result.order_result.client_order_id, result.order_result.status.value, len(result.protective_order_results or ()))"
```

기대 출력:

```text
order_submitted gptrader-dry-run-manual-smoke accepted 2
```

SQLite 런타임 기록은 아래 파일에 저장됩니다.

```text
gptrader-dry-run.sqlite3
```

로그는 아래 경로에 저장됩니다.

```text
logs/YYYY-MM-DD/runtime.log
```

## 5. 로컬 API 서버 실행

dry-run 모드로 API를 실행합니다.

```powershell
C:\Python310\python.exe -m uvicorn src.runtime.local_composition:create_local_app --factory --host 127.0.0.1 --port 8000
```

상태 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/readiness
Invoke-RestMethod http://127.0.0.1:8000/status
```

API로 dry-run trade를 한 번 실행합니다.

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/trade/execute `
  -ContentType 'application/json' `
  -Body '{"signal_id":"api-smoke"}'
```

응답에는 아래 값이 포함되어야 합니다.

```text
ok: true
status: order_submitted
```

## 6. 현재 가능한 범위

현재 바로 실행 가능한 로컬 경로는 `dry-run`입니다.

지원하는 것:

- deterministic local market data 로딩
- 기본 moving-average signal strategy 평가
- ATR 기반 TP/SL 가격 계산
- 진입 주문 의도 기록
- TP/SL 보호 주문 의도 기록
- signal, scheduler, order 기록을 SQLite에 저장

아직 하지 않는 것:

- Binance API 호출
- live 주문 제출
- background scheduler process 실행
- websocket position sync 실행

`docker-compose.yml`은 아직 v2 runtime 기준으로 정리되지 않았습니다.
현재 compose 파일은 legacy root script를 참조하므로, 로컬 실행은 위 Python 명령을 사용하세요.
