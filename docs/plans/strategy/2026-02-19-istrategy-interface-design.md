# IStrategy Interface Design

Date: 2026-02-19  
Module: strategy

## 1. Scope and Decisions

This document defines the common interface for all strategies.

Confirmed decisions:
- `run_strategy` input is standardized as `list[dict]`-based payload.
- Strategy output is always a single decision object.
- Indicator calculation is external to strategy; strategy only consumes provided indicators.
- Strategy logic may only use pre-defined indicator columns from existing indicator module.
- Multi-timeframe inputs are first-class and must include these base timeframes: `1m`, `5m`, `15m`, `30m`, `1h`.
- Candle lookback requirements are provided via config in `init_strategy`.

## 2. Interface Contract

### 2.1 Allowed indicator columns

Allowed keys are fixed to the current indicator module output (`Indicator.get_all` keys):

- `timestamp`
- `ma_fast`, `ma_slow`, `ema_fast`, `ema_slow`, `ema_gap`, `ema_gap_ratio`
- `rsi`
- `macd_line`, `macd_signal_line`, `macd_hist`
- `bollinger_mid`, `bollinger_upper`, `bollinger_lower`, `bollinger_width`
- `true_range`, `atr`
- `dmi_plus_di`, `dmi_minus_di`, `dmi_adx`
- `stochastic_per_k`, `stochastic_per_d`
- `cci`, `roc`, `momentum`, `obv`, `mfi`, `vwap`
- `donchain_upper`, `donchain_lower`
- `keltner_mid`, `keltner_upper`, `keltner_lower`
- `low_linear_regression_slope`, `low_linear_regression_direction`
- `high_linear_regression_slope`, `high_linear_regression_direction`

### 2.2 Type models

```python
from abc import ABC, abstractmethod
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

class IStrategy(ABC):
    @abstractmethod
    def init_strategy(self, config: StrategyInitConfig) -> None:
        ...

    @abstractmethod
    def run_strategy(self, data: StrategyRunInput) -> StrategyDecision:
        ...
```

## 3. init_strategy Responsibilities

`init_strategy(config)` should:

1. Save required config/state:
- `strategy_name`, `symbol`, `timeframes`, `lookback_by_tf`, `params`
- mark initialized state (`_initialized = True`)

2. Validate strategy readiness:
- every configured timeframe exists in `lookback_by_tf`
- each lookback is `>= 1`
- strategy-specific required params exist

3. Build derived runtime state:
- cache required rows per timeframe
- merge defaults + user params

4. Enforce fail-fast policy:
- invalid config raises exception immediately
- `run_strategy` before initialization raises exception

## 4. Recommended Common Helper Methods

Add non-abstract/common helpers in base class for consistency:

- `validate_input(data: StrategyRunInput) -> None`
  - check timeframe presence and minimum row count
- `_latest(tf: TF, col: str) -> Any`
  - read latest indicator value from timeframe
- `_window(tf: TF, n: int) -> List[Dict[str, Any]]`
  - get recent `n` rows per timeframe
- `name() -> str`
  - stable strategy identifier for logs/backtest records

## 5. Error Handling and Backtest Integration

### 5.1 Error handling

Raise exception when:
- `run_strategy` called before `init_strategy`
- required timeframe is missing in `indicators_by_tf`
- provided rows are fewer than `lookback_by_tf[tf]`
- unsupported indicator keys are present

### 5.2 Backtest integration

Backtest engine responsibilities:
- precompute indicators per timeframe
- pass payload as `indicators_by_tf`

Strategy responsibilities:
- no indicator calculation
- return exactly one `StrategyDecision`

## 6. Testing Criteria

1. Unit tests:
- valid input returns `StrategyDecision`
- uninitialized strategy raises exception
- missing timeframe raises exception
- insufficient rows raises exception
- unknown indicator columns raise exception

2. Contract tests:
- `ALLOWED_INDICATOR_COLUMNS` must match actual `Indicator.get_all()` key set

3. Regression tests:
- deterministic output on fixed multi-timeframe sample (`1m`, `5m`, `15m`, `30m`, `1h`)

## 7. Next Step

Create implementation plan for:
- model/class placement
- base class refactor of existing `src/strategy/strategies/IStrategy.py`
- tests for interface contract
- migration path for concrete strategies
