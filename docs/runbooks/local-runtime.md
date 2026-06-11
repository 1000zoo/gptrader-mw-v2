# Local Runtime Runbook

This runbook is for the first safe runtime mode: `local`.
Local mode must not call Binance or submit orders.

## Interpreter

Use Python 3.10 or newer. On the current Windows workspace, the verified command is:

```powershell
C:\Python310\python.exe
```

## Test Command

Run the full test suite before and after runtime wiring changes:

```powershell
C:\Python310\python.exe -m pytest -q
```

## Environment

Start from `.env.example` and keep these defaults for local mode:

```dotenv
GPTRADER_MODE=local
GPTRADER_LIVE_ARMED=false
GPTRADER_SYMBOL=BTCUSDT
GPTRADER_TIMEFRAME=1m
GPTRADER_CANDLE_LIMIT=100
GPTRADER_CLIENT_ORDER_ID_PREFIX=gptrader-local
GPTRADER_GENERATOR_ID=local-generator
GPTRADER_SIGNAL_ID_PREFIX=local-signal
GPTRADER_DB_URL=sqlite:///./gptrader-local.sqlite3
```

## Import Smoke Check

The local composition root can be loaded without external credentials:

```powershell
C:\Python310\python.exe -c "from src.runtime import create_local_app; app = create_local_app(); print(app.title)"
```

Expected output:

```text
Gptrader API
```

## Local Strategy Smoke Check

The local runtime can build a deterministic strategy context and evaluate the example strategy without exchange credentials:

```powershell
C:\Python310\python.exe -c "from src.runtime import evaluate_local_example_strategy, RuntimeSettings; print(evaluate_local_example_strategy(RuntimeSettings()).signal.direction.value)"
```

Expected output:

```text
long
```

## Local Persistence Smoke Check

Runtime state persistence is available through `SqliteRuntimeStateRepository`.
Use a temporary path for smoke checks until the composition root owns schema/bootstrap:

```powershell
C:\Python310\python.exe -c "from src.infrastructure.persistence import SqliteRuntimeStateRepository; repo = SqliteRuntimeStateRepository('runtime-smoke.sqlite3'); repo.append_runtime_record(record_type='smoke', record_id='local', payload={'ok': True}); print(repo.list_runtime_records('smoke')[0].payload['ok'])"
```

Expected output:

```text
True
```

## Local API Server

Once `uvicorn` is installed in the same interpreter, start the local API with:

```powershell
C:\Python310\python.exe -m uvicorn src.runtime.local_composition:create_local_app --factory --host 127.0.0.1 --port 8000
```

Initial endpoints:

- `GET /health`
- `GET /readiness`
- `GET /status`

Do not add live trade controls to local runtime until persistence recovery, mode gating, and testnet rehearsal are complete.
