# IStrategy Interface Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standardize `IStrategy` with validated Pydantic contracts, multi-timeframe indicator input, and fail-fast runtime checks.

**Architecture:** Keep `IStrategy` as the single abstract parent in `src/strategy/strategies/IStrategy.py`, add explicit input/output/config models in a sibling module, and enforce column/timeframe/lookback validation at model + base-class levels. Strategy implementations will consume only externally-calculated indicators and return one decision object.

**Tech Stack:** Python, Pydantic, pytest, pandas-free `list[dict]` payload contract

---

### Task 1: Add strategy contract models

**Files:**
- Create: `src/strategy/strategies/models.py`
- Test: `tests/test_strategy_models.py`

**Step 1: Write the failing test**

```python
import pytest

from src.strategy.strategies.models import StrategyRunInput


def test_strategy_run_input_rejects_unknown_indicator_columns():
    with pytest.raises(ValueError):
        StrategyRunInput(
            indicators_by_tf={
                "1m": [{"timestamp": "2026-01-01T00:00:00Z", "unknown_col": 1.0}],
                "5m": [],
                "15m": [],
                "30m": [],
                "1h": [],
            }
        )
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_models.py::test_strategy_run_input_rejects_unknown_indicator_columns -v`
Expected: FAIL with import/model-not-found error.

**Step 3: Write minimal implementation**

```python
# src/strategy/strategies/models.py
from typing import Any, Dict, List, Literal
from pydantic import BaseModel, Field, model_validator

TF = Literal["1m", "5m", "15m", "30m", "1h"]
Action = Literal["BUY", "SELL", "HOLD"]

ALLOWED_INDICATOR_COLUMNS = {
    "timestamp",
    "ma_fast", "ma_slow", "ema_fast", "ema_slow", "ema_gap", "ema_gap_ratio",
    "rsi",
    "macd_line", "macd_signal_line", "macd_hist",
    "bollinger_mid", "bollinger_upper", "bollinger_lower", "bollinger_width",
    "true_range", "atr",
    "dmi_plus_di", "dmi_minus_di", "dmi_adx",
    "stochastic_per_k", "stochastic_per_d",
    "cci", "roc", "momentum", "obv", "mfi", "vwap",
    "donchain_upper", "donchain_lower",
    "keltner_mid", "keltner_upper", "keltner_lower",
    "low_linear_regression_slope", "low_linear_regression_direction",
    "high_linear_regression_slope", "high_linear_regression_direction",
}

class StrategyInitConfig(BaseModel):
    strategy_name: str
    symbol: str
    timeframes: List[TF] = Field(default_factory=lambda: ["1m", "5m", "15m", "30m", "1h"])
    lookback_by_tf: Dict[TF, int] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)

class StrategyRunInput(BaseModel):
    indicators_by_tf: Dict[TF, List[Dict[str, Any]]]
    recent_analyzes: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_indicator_columns(self):
        for tf, rows in self.indicators_by_tf.items():
            for row in rows:
                unknown = set(row.keys()) - ALLOWED_INDICATOR_COLUMNS
                if unknown:
                    raise ValueError(f"{tf}: unsupported indicator columns: {sorted(unknown)}")
        return self

class StrategyDecision(BaseModel):
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_strategy_models.py::test_strategy_run_input_rejects_unknown_indicator_columns -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/strategy/strategies/models.py tests/test_strategy_models.py
git commit -m "feat: add strategy contract models and column validation"
```

### Task 2: Refactor IStrategy base class to use contracts

**Files:**
- Modify: `src/strategy/strategies/IStrategy.py`
- Test: `tests/test_strategy_base.py`

**Step 1: Write the failing test**

```python
import pytest

from src.strategy.strategies.IStrategy import IStrategy
from src.strategy.strategies.models import StrategyRunInput


class DummyStrategy(IStrategy):
    def init_strategy(self, config):
        super().init_strategy(config)

    def run_strategy(self, data):
        self.validate_input(data)
        return self._hold("ok")


def test_run_strategy_raises_when_not_initialized(sample_input):
    strategy = DummyStrategy()
    with pytest.raises(ValueError):
        strategy.run_strategy(sample_input)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_base.py::test_run_strategy_raises_when_not_initialized -v`
Expected: FAIL because base class helper/guard is missing.

**Step 3: Write minimal implementation**

```python
# src/strategy/strategies/IStrategy.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from src.strategy.strategies.models import TF, StrategyDecision, StrategyInitConfig, StrategyRunInput


class IStrategy(ABC):
    def __init__(self):
        self._initialized = False
        self._config: StrategyInitConfig | None = None

    def init_strategy(self, config: StrategyInitConfig) -> None:
        for tf in config.timeframes:
            if tf not in config.lookback_by_tf:
                raise ValueError(f"lookback is missing for timeframe={tf}")
            if config.lookback_by_tf[tf] < 1:
                raise ValueError(f"lookback must be >= 1 for timeframe={tf}")
        self._config = config
        self._initialized = True

    def validate_input(self, data: StrategyRunInput) -> None:
        if not self._initialized or self._config is None:
            raise ValueError("strategy is not initialized")
        for tf in self._config.timeframes:
            rows = data.indicators_by_tf.get(tf)
            if rows is None:
                raise ValueError(f"missing timeframe indicators: {tf}")
            min_rows = self._config.lookback_by_tf[tf]
            if len(rows) < min_rows:
                raise ValueError(f"insufficient rows for {tf}: need={min_rows}, got={len(rows)}")

    def _latest(self, data: StrategyRunInput, tf: TF, col: str) -> Any:
        return data.indicators_by_tf[tf][-1][col]

    def _window(self, data: StrategyRunInput, tf: TF, n: int) -> List[Dict[str, Any]]:
        return data.indicators_by_tf[tf][-n:]

    def _hold(self, reason: str, metadata: Dict[str, Any] | None = None) -> StrategyDecision:
        return StrategyDecision(action="HOLD", confidence=0.0, reason=reason, metadata=metadata or {})

    def name(self) -> str:
        if self._config is None:
            return self.__class__.__name__
        return self._config.strategy_name

    @abstractmethod
    def run_strategy(self, data: StrategyRunInput) -> StrategyDecision:
        ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_strategy_base.py::test_run_strategy_raises_when_not_initialized -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/strategy/strategies/IStrategy.py tests/test_strategy_base.py
git commit -m "refactor: enforce IStrategy init and input validation"
```

### Task 3: Add comprehensive base behavior tests

**Files:**
- Modify: `tests/test_strategy_base.py`

**Step 1: Write failing tests**

```python
def test_validate_input_raises_on_missing_timeframe():
    ...

def test_validate_input_raises_on_insufficient_rows():
    ...

def test_latest_and_window_helpers_work():
    ...

def test_name_returns_configured_name_after_init():
    ...
```

**Step 2: Run tests to verify failures**

Run: `pytest tests/test_strategy_base.py -v`
Expected: FAIL on missing helper behavior and/or edge conditions.

**Step 3: Implement minimal fixes in base class**

```python
# tighten error messages and helper safeguards
# ensure helper methods raise clear ValueError on invalid col/tf
```

**Step 4: Run tests to verify passes**

Run: `pytest tests/test_strategy_base.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/strategy/strategies/IStrategy.py tests/test_strategy_base.py
git commit -m "test: cover IStrategy base validation and helper methods"
```

### Task 4: Add contract sync test with indicator module

**Files:**
- Create: `tests/test_strategy_indicator_contract.py`

**Step 1: Write failing test**

```python
from src.strategy.strategies.models import ALLOWED_INDICATOR_COLUMNS
from src.common.model.params import IndParams
from src.indicators.engine.indicator import Indicator


def test_allowed_columns_matches_indicator_get_all_keys(sample_ohlcv):
    keys = set(Indicator(sample_ohlcv, IndParams()).get_all().keys())
    assert keys == ALLOWED_INDICATOR_COLUMNS
```

**Step 2: Run test to verify it fails if mismatch exists**

Run: `pytest tests/test_strategy_indicator_contract.py::test_allowed_columns_matches_indicator_get_all_keys -v`
Expected: FAIL initially if any naming mismatch exists.

**Step 3: Fix contract mismatch minimally**

```python
# update ALLOWED_INDICATOR_COLUMNS only
# do not add new indicator names outside current indicator module
```

**Step 4: Run test to verify pass**

Run: `pytest tests/test_strategy_indicator_contract.py::test_allowed_columns_matches_indicator_get_all_keys -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_strategy_indicator_contract.py src/strategy/strategies/models.py
git commit -m "test: enforce strategy indicator column contract"
```

### Task 5: Final verification and docs touch-up

**Files:**
- Modify: `docs/plans/strategy/2026-02-19-istrategy-interface-design.md` (only if implementation detail changed)

**Step 1: Run targeted tests**

Run: `pytest tests/test_strategy_models.py tests/test_strategy_base.py tests/test_strategy_indicator_contract.py -v`
Expected: PASS.

**Step 2: Run broader safety tests**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS.

**Step 3: Update design doc if contract changed during implementation**

```markdown
- keep contract doc synced with final code
```

**Step 4: Commit verification/doc sync**

```bash
git add docs/plans/strategy/2026-02-19-istrategy-interface-design.md
git commit -m "docs: sync strategy design with implemented contract"
```

