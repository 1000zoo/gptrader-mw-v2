# Local Setup Guide

This guide starts the current local runtime from a clean checkout on Windows.
It uses `dry-run` mode for the first executable path: the real trade lifecycle
runs, TP/SL protective orders are calculated and recorded, but no Binance API
request is sent.

## 1. Prerequisites

Use Python 3.10 or newer. In this workspace, the verified interpreter is:

```powershell
C:\Python310\python.exe
```

Do not use the default `python` if it points to Python 3.9. The codebase uses
Python 3.10 syntax such as `A | None`.

Confirm the interpreter and required packages:

```powershell
C:\Python310\python.exe --version
C:\Python310\python.exe -c "import fastapi, uvicorn, pytest; print('deps ok')"
```

If dependencies are missing:

```powershell
C:\Python310\python.exe -m pip install -r requirements.txt
```

## 2. Environment

Copy the sample environment file if you want a local `.env`:

```powershell
Copy-Item .env.example .env
```

For safe local execution, use these values:

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

Binance keys are not required for `local` or `dry-run` mode.

## 3. Verify Tests

Run the full test suite before starting the runtime:

```powershell
C:\Python310\python.exe -m pytest -q
```

Expected result:

```text
269 passed
```

## 4. Smoke Run Trade Lifecycle

This command runs the entry lifecycle once. It should create one dry-run entry
order plus two dry-run Binance-style protective orders:

- `TAKE_PROFIT_MARKET`
- `STOP_MARKET`

Both protective orders are recorded locally with `closePosition=true` semantics.

```powershell
C:\Python310\python.exe -c "import os; from src.runtime import RuntimeSettings, create_local_runtime; runtime=create_local_runtime(RuntimeSettings.from_env(os.environ)); result=runtime.run_trade_execution_once('manual-smoke'); print(result.status.value, result.order_result.client_order_id, result.order_result.status.value, len(result.protective_order_results or ()))"
```

Expected output starts with:

```text
order_submitted gptrader-dry-run-manual-smoke accepted 2
```

Runtime records are written to:

```text
gptrader-dry-run.sqlite3
```

Logs are written under:

```text
logs/YYYY-MM-DD/runtime.log
```

## 5. Start Local API

Start the API in dry-run mode:

```powershell
C:\Python310\python.exe -m uvicorn src.runtime.local_composition:create_local_app --factory --host 127.0.0.1 --port 8000
```

Check health endpoints:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/readiness
Invoke-RestMethod http://127.0.0.1:8000/status
```

Trigger one dry-run trade through the API:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/trade/execute `
  -ContentType 'application/json' `
  -Body '{"signal_id":"api-smoke"}'
```

Expected response includes:

```text
ok: true
status: order_submitted
```

## 6. Current Runtime Boundaries

`dry-run` mode is the supported local execution path right now.

It does:

- load deterministic local market data;
- evaluate the default moving-average signal strategy;
- calculate ATR-based TP/SL levels;
- record the intended entry order;
- record intended TP/SL protective orders;
- persist signal, scheduler, and order records to SQLite.

It does not:

- call Binance;
- place live orders;
- run a background scheduler process;
- run websocket position sync.

The repository has a `docker-compose.yml`, but the current compose file still
references legacy root scripts that are not present in this v2 runtime path.
Use the Python commands above until the process layout is updated.
