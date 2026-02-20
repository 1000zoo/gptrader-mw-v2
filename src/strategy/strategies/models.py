from typing import TYPE_CHECKING, Any, Dict, List, Literal, cast

from pydantic import BaseModel

try:
    from pydantic import Field
except ImportError:
    def Field(default=None, default_factory=None, **kwargs):
        if default_factory is not None:
            return default_factory()
        return default

if TYPE_CHECKING:
    from src.binance.vo.ohlcv.default import DefaultOhlcvVo

TF = Literal["1m", "5m", "15m", "30m", "1h"]
Action = Literal["BUY", "SELL", "HOLD"]

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
    symbol: str
    timeframes: List[TF] = Field(default_factory=lambda: ["1m", "5m", "15m", "30m", "1h"])
    lookback_by_tf: Dict[TF, int] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)


class StrategyRunInput(BaseModel):
    indicators_by_tf: Dict[TF, List[Dict[str, Any]]]
    ohlcv_by_tf: Dict[TF, Dict[str, Any]]
    recent_analyzes: List[Dict[str, Any]] = Field(default_factory=list)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        for tf, rows in self.indicators_by_tf.items():
            for row in rows:
                unknown = set(row.keys()) - ALLOWED_INDICATOR_COLUMNS
                if unknown:
                    raise ValueError(f"{tf}: unsupported indicator columns: {sorted(unknown)}")

        for tf, row in self.ohlcv_by_tf.items():
            unknown = set(row.keys()) - ALLOWED_OHLCV_COLUMNS
            if unknown:
                raise ValueError(f"{tf}: unsupported ohlcv columns: {sorted(unknown)}")

    @staticmethod
    def ohlcv_vo_to_dict(vo: "DefaultOhlcvVo") -> Dict[str, Any]:
        return {
            "timestamp": vo.ts,
            "open": vo.c_open,
            "high": vo.c_high,
            "low": vo.c_low,
            "close": vo.c_close,
            "volume": vo.volume,
            "quote_volume": vo.quote_volume,
        }

    @staticmethod
    def ohlcv_by_tf_from_vo_list(vo_list: List["DefaultOhlcvVo"]) -> Dict[TF, Dict[str, Any]]:
        res: Dict[TF, Dict[str, Any]] = {}
        for vo in vo_list:
            tf = vo.c_interval
            if tf not in {"1m", "5m", "15m", "30m", "1h"}:
                continue
            res[cast(TF, tf)] = StrategyRunInput.ohlcv_vo_to_dict(vo)
        return res


class StrategyDecision(BaseModel):
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("confidence must be between 0 and 1")
