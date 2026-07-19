# Module J Ports Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define domain-level external dependency ports for market data, account state, order execution, strategy persistence, and signal logging.

**Architecture:** Add Protocol-based contracts under `src/domain/ports` with small immutable data models where no existing domain model exists. Ports only depend on domain models and Python standard library types, leaving concrete exchange, database, and logging behavior to infrastructure modules.

**Tech Stack:** Python dataclasses, `typing.Protocol`, pytest.

---

### Task 1: Market Data Port

**Files:**
- Create: `src/domain/ports/market_data_port.py`
- Create: `src/domain/ports/__init__.py`
- Test: `tests/domain/ports/test_market_data_port.py`

**Step 1: Write the failing test**

```python
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.ports import MarketDataPort


def make_candle() -> Candle:
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    opened_at = datetime(2026, 1, 1, 0, 0)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=1),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("105"),
        volume=Decimal("12"),
    )


class InMemoryMarketDataPort:
    def __init__(self, candles: tuple[Candle, ...]) -> None:
        self.candles = candles

    def load_candles(self, symbol: Symbol, timeframe: Timeframe, limit: int) -> tuple[Candle, ...]:
        return self.candles[:limit]

    def load_snapshot(self, symbol: Symbol, timeframe: Timeframe, limit: int) -> MarketSnapshot:
        return MarketSnapshot(self.load_candles(symbol, timeframe, limit))


def test_market_data_port_is_protocol_contract():
    assert issubclass(MarketDataPort, Protocol)


def test_market_data_port_loads_candles_and_snapshot():
    candle = make_candle()
    port = InMemoryMarketDataPort((candle,))

    candles = port.load_candles(candle.symbol, candle.timeframe, limit=1)
    snapshot = port.load_snapshot(candle.symbol, candle.timeframe, limit=1)

    assert isinstance(port, MarketDataPort)
    assert candles == (candle,)
    assert snapshot.latest_candle == candle
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/ports/test_market_data_port.py -v`
Expected: FAIL because `src.domain.ports` does not exist.

**Step 3: Write minimal implementation**

Create `MarketDataPort` as a runtime-checkable `Protocol` with `load_candles` and `load_snapshot`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/ports/test_market_data_port.py -v`
Expected: PASS.

### Task 2: Account and Order Execution Ports

**Files:**
- Create: `src/domain/ports/account_port.py`
- Create: `src/domain/ports/order_execution_port.py`
- Modify: `src/domain/ports/__init__.py`
- Test: `tests/domain/ports/test_account_port.py`
- Test: `tests/domain/ports/test_order_execution_port.py`

**Step 1: Write failing tests**

Define tests for `AccountSnapshot`, `AssetBalance`, `AccountPort`, and `OrderExecutionPort`.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/domain/ports/test_account_port.py tests/domain/ports/test_order_execution_port.py -v`
Expected: FAIL because modules are missing.

**Step 3: Write minimal implementation**

Add immutable account balance models and runtime-checkable protocols. `OrderExecutionPort.submit_order` returns `OrderResult`; `load_execution_reports` returns `ExecutionReport` values.

**Step 4: Run tests**

Run: `pytest tests/domain/ports/test_account_port.py tests/domain/ports/test_order_execution_port.py -v`
Expected: PASS.

### Task 3: Repository Ports

**Files:**
- Create: `src/domain/ports/strategy_repository_port.py`
- Create: `src/domain/ports/signal_log_repository_port.py`
- Modify: `src/domain/ports/__init__.py`
- Test: `tests/domain/ports/test_strategy_repository_port.py`
- Test: `tests/domain/ports/test_signal_log_repository_port.py`

**Step 1: Write failing tests**

Define tests for storing and loading `StrategyDefinition`, `SignalGeneratorDefinition`, `StrategyEvaluation`, and `GeneratedSignal`.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/domain/ports/test_strategy_repository_port.py tests/domain/ports/test_signal_log_repository_port.py -v`
Expected: FAIL because modules are missing.

**Step 3: Write minimal implementation**

Add repository Protocols with explicit save/load/list method names and no persistence implementation.

**Step 4: Run tests**

Run: `pytest tests/domain/ports/test_strategy_repository_port.py tests/domain/ports/test_signal_log_repository_port.py -v`
Expected: PASS.

### Task 4: Full Verification and Progress Update

**Files:**
- Modify: `docs/progress.md`

**Step 1: Run focused tests**

Run: `pytest tests/domain/ports -v`
Expected: PASS.

**Step 2: Run full domain tests**

Run: `pytest tests/domain -v`
Expected: PASS.

**Step 3: Update progress**

Change Module J status from `in progress` to `done` and add a work log entry with this plan path.
