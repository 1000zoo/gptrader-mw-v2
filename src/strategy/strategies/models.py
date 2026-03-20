from typing import Any, Dict, List

from pydantic import BaseModel

from src.common.model.types import TF, Action

ALLOWED_INDICATOR_COLUMNS = {
    "timestamp",
    "ma_fast",
    "ma_slow",
    "ema_fast",
    "ema_slow",
    "ema_gap",
    "ema_gap_ratio",
    "rsi",
    "macd_line",
    "macd_signal_line",
    "macd_hist",
    "bollinger_mid",
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_width",
    "true_range",
    "atr",
    "dmi_plus_di",
    "dmi_minus_di",
    "dmi_adx",
    "stochastic_per_k",
    "stochastic_per_d",
    "cci",
    "roc",
    "momentum",
    "obv",
    "mfi",
    "vwap",
    "donchain_upper",
    "donchain_lower",
    "keltner_mid",
    "keltner_upper",
    "keltner_lower",
    "low_linear_regression_slope",
    "low_linear_regression_direction",
    "high_linear_regression_slope",
    "high_linear_regression_direction",
}

ALLOWED_OHLCV_COLUMNS = {
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
}


class StrategyInitConfig(BaseModel):
    strategy_name: str
    symbol: str = "ANY"
    timeframes: List[TF]
    lookback_by_tf: Dict[TF, int]
    params: Dict[str, Any] = {}
    limit: Dict[TF, int] = {}


class StrategyRunInput(BaseModel):
    indicators_by_tf: Dict[TF, List[Dict[str, Any]]]
    ohlcv_by_tf: Dict[TF, Dict[str, Any]]
    recent_analyzes: List[Dict[str, Any]] = []


class StrategyDecision(BaseModel):
    action: Action
    confidence: float
    reason: str
    metadata: Dict[str, Any] = {}
