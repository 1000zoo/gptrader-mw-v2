# Strategy Backtest Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a lifecycle pipeline that registers cataloged strategy candidates, runs recent-lookback backtests for each one, saves `BACKTESTED` evaluations, and leaves promotion to the existing lifecycle use case.

**Architecture:** Add an explicit strategy catalog in the domain strategy implementation area, then add a strategy lifecycle use case that coordinates catalog specs, research backtests, evaluation creation, and repository persistence. Keep backtest execution in `application/usecases/research`; keep promotion in the existing lifecycle promotion use case.

**Tech Stack:** Python dataclasses, Protocol-compatible strategy classes, existing `MarketDataPort`, existing `StrategyRepositoryPort`, pytest.

**Implementation Status:** Implemented. Checked items below represent completed TDD and documentation steps; red-phase failure expectations are retained as historical verification notes from the original implementation sequence.

---

## File Structure

- Create `src/domain/strategy/strategy_spec.py`: immutable `StrategySpec` model and validation.
- Create `src/domain/strategy/strategy_catalog.py`: catalog protocol and code-native catalog implementation.
- Modify `src/domain/strategy/__init__.py`: export `StrategySpec`, `StrategyCatalog`, and `StaticStrategyCatalog`.
- Modify `src/domain/strategy/implementations/__init__.py`: provide default catalog factory or exported catalog entries.
- Create `tests/domain/strategy/test_strategy_catalog.py`: catalog/spec tests.
- Modify `src/application/usecases/strategy_lifecycle/dto.py`: add batch backtest cycle command/result DTOs.
- Create `src/application/usecases/strategy_lifecycle/run_strategy_backtest_cycle_usecase.py`: orchestration use case.
- Modify `src/application/usecases/strategy_lifecycle/__init__.py`: export new DTOs/use case.
- Create `tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py`: use case tests.
- Modify `docs/plans/application/strategy_lifecycle/latest.md`: mark the new pipeline as planned/current follow-up.
- Modify `src/interfaces/scheduler/strategy_lifecycle_scheduler.py`: expose a scheduler entry point for the backtest cycle.
- Modify `tests/interfaces/scheduler/test_strategy_lifecycle_scheduler.py`: cover backtest-cycle scheduler records and errors.

## Task 1: StrategySpec Model

**Files:**
- Create: `src/domain/strategy/strategy_spec.py`
- Modify: `src/domain/strategy/__init__.py`
- Test: `tests/domain/strategy/test_strategy_catalog.py`

- [x] **Step 1: Write the failing test**

```python
from decimal import Decimal

import pytest

from src.domain.market import Symbol, Timeframe
from src.domain.strategy import StrategySpec


def test_strategy_spec_stores_candidate_metadata():
    spec = StrategySpec(
        strategy_id="session-volume-profile",
        name="Session Volume Profile",
        implementation="src.domain.strategy.implementations.SessionVolumeProfileStrategy",
        version="2026.06.17",
        symbol=Symbol("BTC", "USDT"),
        timeframe=Timeframe(5, "m"),
        lookback_candle_limit=25920,
        parameters={"price_bin_size": Decimal("10")},
        metadata={"family": "volume_profile"},
    )

    assert spec.strategy_id == "session-volume-profile"
    assert spec.name == "Session Volume Profile"
    assert spec.lookback_candle_limit == 25920
    assert spec.parameters["price_bin_size"] == Decimal("10")
    assert spec.metadata["family"] == "volume_profile"


def test_strategy_spec_rejects_blank_ids_and_invalid_lookback():
    with pytest.raises(ValueError, match="strategy_id"):
        StrategySpec(
            strategy_id=" ",
            name="Name",
            implementation="impl",
            version="1",
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            lookback_candle_limit=1,
        )

    with pytest.raises(ValueError, match="lookback_candle_limit"):
        StrategySpec(
            strategy_id="strategy-1",
            name="Name",
            implementation="impl",
            version="1",
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            lookback_candle_limit=0,
        )
```

- [x] **Step 2: Run test to verify it fails**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/domain/strategy/test_strategy_catalog.py -v`

Expected: FAIL because `StrategySpec` is not exported from `src.domain.strategy`.

- [x] **Step 3: Implement StrategySpec**

```python
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from src.domain.market import Symbol, Timeframe


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    name: str
    implementation: str
    version: str
    symbol: Symbol
    timeframe: Timeframe
    lookback_candle_limit: int
    parameters: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        strategy_id = self.strategy_id.strip()
        name = self.name.strip()
        implementation = self.implementation.strip()
        version = self.version.strip()
        if not strategy_id:
            raise ValueError("strategy_id is required")
        if not name:
            raise ValueError("name is required")
        if not implementation:
            raise ValueError("implementation is required")
        if not version:
            raise ValueError("version is required")
        if self.lookback_candle_limit <= 0:
            raise ValueError("lookback_candle_limit must be positive")

        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "implementation", implementation)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
```

Export it from `src/domain/strategy/__init__.py`:

```python
from src.domain.strategy.strategy_spec import StrategySpec
```

- [x] **Step 4: Run test to verify it passes**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/domain/strategy/test_strategy_catalog.py -v`

Expected: PASS.

## Task 2: Static Strategy Catalog

**Files:**
- Create: `src/domain/strategy/strategy_catalog.py`
- Modify: `src/domain/strategy/__init__.py`
- Modify: `src/domain/strategy/implementations/__init__.py`
- Test: `tests/domain/strategy/test_strategy_catalog.py`

- [x] **Step 1: Add failing catalog tests**

```python
from decimal import Decimal

from src.domain.strategy import StaticStrategyCatalog
from src.domain.strategy.implementations import (
    LatestCloseMovingAverageStrategy,
    SessionVolumeProfileStrategy,
    create_default_strategy_catalog,
)


def test_static_strategy_catalog_lists_specs_in_stable_order():
    catalog = create_default_strategy_catalog()

    specs = catalog.list_specs()

    assert tuple(spec.strategy_id for spec in specs) == (
        "latest-close-moving-average",
        "session-volume-profile",
    )


def test_static_strategy_catalog_instantiates_strategy_from_spec():
    catalog = create_default_strategy_catalog()
    specs = {spec.strategy_id: spec for spec in catalog.list_specs()}

    moving_average = catalog.create_strategy(specs["latest-close-moving-average"])
    profile = catalog.create_strategy(specs["session-volume-profile"])

    assert isinstance(moving_average, LatestCloseMovingAverageStrategy)
    assert isinstance(profile, SessionVolumeProfileStrategy)


def test_static_strategy_catalog_applies_spec_parameters():
    catalog = StaticStrategyCatalog(
        entries=(
            (
                StrategySpec(
                    strategy_id="session-volume-profile",
                    name="Session Volume Profile",
                    implementation="src.domain.strategy.implementations.SessionVolumeProfileStrategy",
                    version="2026.06.17",
                    symbol=Symbol("BTC", "USDT"),
                    timeframe=Timeframe(5, "m"),
                    lookback_candle_limit=100,
                    parameters={"price_bin_size": Decimal("25")},
                ),
                SessionVolumeProfileStrategy,
            ),
        )
    )

    strategy = catalog.create_strategy(catalog.list_specs()[0])

    assert isinstance(strategy, SessionVolumeProfileStrategy)
    assert strategy.price_bin_size == Decimal("25")
```

- [x] **Step 2: Run test to verify it fails**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/domain/strategy/test_strategy_catalog.py -v`

Expected: FAIL because `StaticStrategyCatalog` and `create_default_strategy_catalog` do not exist.

- [x] **Step 3: Implement catalog**

```python
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from src.domain.strategy.strategy import Strategy
from src.domain.strategy.strategy_spec import StrategySpec


StrategyFactory = Callable[..., Strategy]


@runtime_checkable
class StrategyCatalog(Protocol):
    def list_specs(self) -> tuple[StrategySpec, ...]:
        ...

    def create_strategy(self, spec: StrategySpec) -> Strategy:
        ...


@dataclass(frozen=True)
class StaticStrategyCatalog:
    entries: tuple[tuple[StrategySpec, StrategyFactory], ...]

    def list_specs(self) -> tuple[StrategySpec, ...]:
        return tuple(spec for spec, _factory in self.entries)

    def create_strategy(self, spec: StrategySpec) -> Strategy:
        for candidate, factory in self.entries:
            if candidate.strategy_id == spec.strategy_id:
                return factory(**dict(spec.parameters))
        raise KeyError(f"unknown strategy spec: {spec.strategy_id}")
```

Export `StrategyCatalog` and `StaticStrategyCatalog` from `src/domain/strategy/__init__.py`.

Add `create_default_strategy_catalog()` in `src/domain/strategy/implementations/__init__.py` using explicit entries for:

- `LatestCloseMovingAverageStrategy`
- `SessionVolumeProfileStrategy`

- [x] **Step 4: Run test to verify it passes**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/domain/strategy/test_strategy_catalog.py -v`

Expected: PASS.

## Task 3: Backtest Cycle DTOs

**Files:**
- Modify: `src/application/usecases/strategy_lifecycle/dto.py`
- Test: `tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py`

- [x] **Step 1: Write failing DTO tests**

```python
from src.application.usecases.strategy_lifecycle import (
    RunStrategyBacktestCycleCommand,
    StrategyBacktestCycleItem,
    RunStrategyBacktestCycleResult,
)


def test_run_strategy_backtest_cycle_command_stores_cycle_inputs():
    command = RunStrategyBacktestCycleCommand(
        cycle_id="cycle-20260617",
        metadata={"lookback": "recent"},
    )

    assert command.cycle_id == "cycle-20260617"
    assert command.metadata["lookback"] == "recent"


def test_run_strategy_backtest_cycle_result_splits_successes_and_failures():
    success = StrategyBacktestCycleItem(
        strategy_id="strategy-1",
        evaluation_id="eval-1",
        succeeded=True,
    )
    failure = StrategyBacktestCycleItem(
        strategy_id="strategy-2",
        evaluation_id=None,
        succeeded=False,
        error_type="RuntimeError",
        error_message="boom",
    )

    result = RunStrategyBacktestCycleResult(items=(success, failure))

    assert result.succeeded_count == 1
    assert result.failed_count == 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py -v`

Expected: FAIL because the DTOs do not exist.

- [x] **Step 3: Implement DTOs**

Add frozen dataclasses:

```python
@dataclass(frozen=True)
class RunStrategyBacktestCycleCommand:
    cycle_id: str
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class StrategyBacktestCycleItem:
    strategy_id: str
    evaluation_id: str | None
    succeeded: bool
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class RunStrategyBacktestCycleResult:
    items: tuple[StrategyBacktestCycleItem, ...]

    @property
    def succeeded_count(self) -> int:
        return sum(1 for item in self.items if item.succeeded)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if not item.succeeded)
```

Apply the same id stripping and metadata defensive copying style used by existing DTOs.

- [x] **Step 4: Export DTOs**

Modify `src/application/usecases/strategy_lifecycle/__init__.py` to export all three DTOs.

- [x] **Step 5: Run test to verify it passes**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py -v`

Expected: PASS.

## Task 4: RunStrategyBacktestCycleUseCase

**Files:**
- Create: `src/application/usecases/strategy_lifecycle/run_strategy_backtest_cycle_usecase.py`
- Modify: `src/application/usecases/strategy_lifecycle/__init__.py`
- Test: `tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py`

- [x] **Step 1: Add failing orchestration test**

```python
from decimal import Decimal

from src.application.usecases.strategy_lifecycle import (
    RunStrategyBacktestCycleCommand,
    RunStrategyBacktestCycleUseCase,
)
from src.domain.indicator import IndicatorSet
from src.domain.lifecycle import StrategyLifecycleStatus
from tests.domain.strategy.test_strategy_context import make_market


def test_backtest_cycle_registers_definitions_and_saves_backtested_evaluations():
    market = make_market()
    repository = FakeStrategyRepository()
    catalog = make_catalog_with_always_long_strategy(market)
    usecase = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=FakeMarketData(market),
        strategy_catalog=catalog,
        indicator_factory=lambda spec, snapshot: IndicatorSet(
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            measured_at=snapshot.latest_candle.closed_at,
            values=(),
        ),
    )

    result = usecase.execute(RunStrategyBacktestCycleCommand(cycle_id="cycle-1"))

    assert result.succeeded_count == 1
    assert repository.saved_definitions[0].strategy_id == "always-long"
    assert repository.saved_evaluations[0].target_id == "always-long"
    assert repository.saved_evaluations[0].status is StrategyLifecycleStatus.BACKTESTED
    assert repository.saved_evaluations[0].metrics["signal_confidence"] == Decimal("0.70")
```

Include fake repository, fake market data, and fake catalog in the test file.

- [x] **Step 2: Run test to verify it fails**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py -v`

Expected: FAIL because `RunStrategyBacktestCycleUseCase` does not exist.

- [x] **Step 3: Implement use case**

`RunStrategyBacktestCycleUseCase.__init__` should receive:

- `strategy_repository: StrategyRepositoryPort`
- `market_data: MarketDataPort`
- `strategy_catalog: StrategyCatalog`
- `indicator_factory: Callable[[StrategySpec, MarketSnapshot], IndicatorSet]`

`execute()` should:

1. iterate `strategy_catalog.list_specs()`;
2. save `StrategyDefinition` for each spec;
3. load snapshot through `market_data.load_snapshot(...)`;
4. build indicators through the injected factory;
5. instantiate strategy through `strategy_catalog.create_strategy(spec)`;
6. call `BacktestStrategyUseCase`;
7. call `EvaluateStrategyUseCase` with `ResearchRunMode.BACKTEST`;
8. save evaluation;
9. append a successful `StrategyBacktestCycleItem`.

Use evaluation ids formatted as:

```python
f"{command.cycle_id}:{spec.strategy_id}:backtest"
```

Metrics:

```python
{
    "signal_confidence": strategy_result.signal.confidence,
    "direction_score": Decimal("0") if strategy_result.signal.direction is SignalDirection.WAIT else Decimal("1"),
    "reason_count": Decimal(len(strategy_result.signal.reasons)),
}
```

- [x] **Step 4: Capture per-strategy failures**

Wrap the per-spec body in `try/except Exception as exc`, append a failed item, and continue to the next spec. Do not swallow repository failures from `save_strategy_evaluation`; allow those to raise after the specific failure has been identified in tests if repository behavior demands it.

- [x] **Step 5: Export use case**

Modify `src/application/usecases/strategy_lifecycle/__init__.py`:

```python
from src.application.usecases.strategy_lifecycle.run_strategy_backtest_cycle_usecase import (
    RunStrategyBacktestCycleUseCase,
)
```

- [x] **Step 6: Run test to verify it passes**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py -v`

Expected: PASS.

## Task 5: Failure Isolation

**Files:**
- Modify: `tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py`
- Modify: `src/application/usecases/strategy_lifecycle/run_strategy_backtest_cycle_usecase.py`

- [x] **Step 1: Add failing failure-isolation test**

```python
def test_backtest_cycle_continues_after_one_strategy_fails():
    market = make_market()
    repository = FakeStrategyRepository()
    catalog = make_catalog_with_failing_and_wait_strategies(market)
    usecase = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=FakeMarketData(market),
        strategy_catalog=catalog,
        indicator_factory=empty_indicator_factory,
    )

    result = usecase.execute(RunStrategyBacktestCycleCommand(cycle_id="cycle-1"))

    assert result.succeeded_count == 1
    assert result.failed_count == 1
    assert result.items[0].strategy_id == "failing"
    assert result.items[0].error_type == "RuntimeError"
    assert result.items[1].strategy_id == "always-wait"
    assert len(repository.saved_evaluations) == 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py::test_backtest_cycle_continues_after_one_strategy_fails -v`

Expected: FAIL if the use case stops on first strategy failure.

- [x] **Step 3: Implement failure isolation**

Keep the `try/except` around one strategy candidate only. The failed item should include:

- `strategy_id`
- `evaluation_id=None`
- `succeeded=False`
- `error_type=type(exc).__name__`
- `error_message=str(exc)`

- [x] **Step 4: Run test to verify it passes**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py -v`

Expected: PASS.

## Task 6: Scheduler Planning Hook

**Files:**
- Modify: `docs/plans/interfaces/scheduler/latest.md`
- Optional later code: `src/interfaces/scheduler/strategy_lifecycle_scheduler.py`

- [x] **Step 1: Update scheduler plan only**

Add a follow-up note that scheduled lifecycle should eventually run:

1. strategy backtest cycle;
2. promotion cycle per strategy target.

Do not modify scheduler code in this task unless a concrete command factory already exists for market data, indicators, catalog, and repository wiring.

- [x] **Step 2: Run docs placeholder scan**

Run:

```powershell
$pattern = "TB" + "D|TO" + "DO|implement" + " later|fill" + " in details"
rg $pattern docs/plans/application/strategy_lifecycle docs/plans/interfaces/scheduler/latest.md
```

Expected: no matches.

## Task 7: Full Verification

**Files:**
- Verify all modified files.

- [x] **Step 1: Run focused tests**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/domain/strategy tests/application/usecases/strategy_lifecycle -v`

Expected: PASS.

- [x] **Step 2: Run full suite**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest`

Expected: PASS.

- [x] **Step 3: Review tracked and untracked worktree state**

Run: `git -c safe.directory=C:/Users/cjswl/prog/gptrader/gptrader-mw-v2 status --short`

Expected: output includes modified tracked files and any new untracked files that belong to the backtest cycle, catalog, strategy implementation, tests, and planning updates.

Run: `git -c safe.directory=C:/Users/cjswl/prog/gptrader/gptrader-mw-v2 ls-files --others --exclude-standard`

Expected: output includes new files that would be missed by a tracked-file-only diff review.

- [x] **Step 4: Review git diff**

Run: `git -c safe.directory=C:/Users/cjswl/prog/gptrader/gptrader-mw-v2 diff -- src tests docs`

Expected: diff only contains catalog, backtest cycle, tests, and planning updates.

## Task 8: Post-Review Indicator Contract Hardening

**Files:**
- Modify: `src/domain/strategy/strategy_spec.py`
- Modify: `src/domain/strategy/implementations/__init__.py`
- Modify: `src/application/usecases/strategy_lifecycle/run_strategy_backtest_cycle_usecase.py`
- Modify: `tests/domain/strategy/test_strategy_catalog.py`
- Modify: `tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py`

- [x] **Step 1: Add regression coverage for explicit indicator requirements**

Add tests proving `StrategySpec.indicator_keys` is normalized and defensively copied, the default catalog declares `moving_average.period_3`, and a custom moving-average strategy can declare `moving_average.period_4`.

- [x] **Step 2: Implement `StrategySpec.indicator_keys`**

Store catalog-level indicator requirements as a normalized tuple. Reject blank and duplicate keys.

- [x] **Step 3: Build declared moving-average indicators**

Update the backtest-cycle indicator builder to read `spec.indicator_keys` and calculate declared `moving_average.period_N` values from the latest N closes when enough candles exist.

- [x] **Step 4: Verify focused tests**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/domain/strategy/test_strategy_catalog.py tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py -q`

Expected: PASS.

## Task 9: Post-Review Scheduler Entry Point

**Files:**
- Modify: `src/interfaces/scheduler/strategy_lifecycle_scheduler.py`
- Modify: `src/interfaces/scheduler/__init__.py`
- Modify: `tests/interfaces/scheduler/test_strategy_lifecycle_scheduler.py`

- [x] **Step 1: Add scheduler tests for backtest cycle execution**

Add tests proving the scheduler calls `RunStrategyBacktestCycleUseCase` with a factory-created command and returns command/result/error/timestamps in an immutable run record.

- [x] **Step 2: Add scheduler error capture tests**

Add tests for command factory errors and missing backtest-cycle use case configuration.

- [x] **Step 3: Implement `run_backtest_cycle`**

Extend `StrategyLifecycleScheduler` with an optional `run_strategy_backtest_cycle_usecase` dependency and a `run_backtest_cycle()` method. Preserve existing lifecycle-only constructor behavior.

- [x] **Step 4: Verify scheduler tests**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests/interfaces/scheduler/test_strategy_lifecycle_scheduler.py -q`

Expected: PASS.
