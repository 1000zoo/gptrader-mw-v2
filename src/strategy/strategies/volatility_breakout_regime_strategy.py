from __future__ import annotations

from typing import Any, Dict, Optional

from src.strategy.strategies.IStrategy import IStrategy
from src.strategy.strategies.models import StrategyDecision, StrategyInitConfig, StrategyRunInput


class VolatilityBreakoutRegimeStrategy(IStrategy):
    """Trend-filtered volatility breakout entry strategy (entry-only mapping)."""

    def __init__(self):
        super().__init__()
        self.tf = "5m"
        self.short_adx_min = 20.0
        self.long_adx_min = 22.0
        self.atr_ratio_min = 0.004
        self.short_rsi_min = 57.0
        self.long_rsi_max = 43.0

    def init_strategy(self, config: StrategyInitConfig) -> None:
        super().init_strategy(config)
        params = config.params or {}
        self.tf = str(params.get("timeframe", self.tf))
        self.short_adx_min = float(params.get("short_adx_min", self.short_adx_min))
        self.long_adx_min = float(params.get("long_adx_min", self.long_adx_min))
        self.atr_ratio_min = float(params.get("atr_ratio_min", self.atr_ratio_min))
        self.short_rsi_min = float(params.get("short_rsi_min", self.short_rsi_min))
        self.long_rsi_max = float(params.get("long_rsi_max", self.long_rsi_max))

        if self.tf not in config.timeframes:
            raise ValueError(f"configured timeframe is missing in timeframes: {self.tf}")

    def run_strategy(self, data: StrategyRunInput) -> StrategyDecision:
        self.validate_input(data)

        indicator = self._latest_row(data, self.tf)
        ohlcv = data.ohlcv_by_tf.get(self.tf, {})

        ema_fast = self._to_float(indicator.get("ema_fast"))
        ema_slow = self._to_float(indicator.get("ema_slow"))
        adx = self._to_float(indicator.get("dmi_adx"))
        atr = self._to_float(indicator.get("atr"))
        rsi = self._to_float(indicator.get("rsi"))
        bb_upper = self._to_float(indicator.get("bollinger_upper"))
        bb_lower = self._to_float(indicator.get("bollinger_lower"))
        close = self._to_float(ohlcv.get("close"))
        volume = self._to_float(ohlcv.get("volume"))

        required = [ema_fast, ema_slow, adx, atr, rsi, bb_upper, bb_lower, close, volume]
        if any(v is None for v in required):
            return self._hold("missing_required_fields")

        if close <= 0 or volume <= 0:
            return self._hold("invalid_market_data")

        atr_ratio = atr / close
        metadata = {
            "timeframe": self.tf,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "adx": adx,
            "atr_ratio": atr_ratio,
            "rsi": rsi,
            "close": close,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
        }

        short_entry = (
            ema_fast < ema_slow
            and adx > self.short_adx_min
            and atr_ratio > self.atr_ratio_min
            and close > bb_upper
            and rsi > self.short_rsi_min
        )
        if short_entry:
            return StrategyDecision(
                action="SELL",
                confidence=self._confidence(adx, atr_ratio),
                reason="vol_breakout_short",
                metadata=metadata,
            )

        long_entry = (
            ema_fast > ema_slow
            and adx > self.long_adx_min
            and atr_ratio > self.atr_ratio_min
            and close < bb_lower
            and rsi < self.long_rsi_max
        )
        if long_entry:
            return StrategyDecision(
                action="BUY",
                confidence=self._confidence(adx, atr_ratio),
                reason="vol_breakout_long",
                metadata=metadata,
            )

        return self._hold("no_entry_signal", metadata=metadata)

    def _latest_row(self, data: StrategyRunInput, tf: str) -> Dict[str, Any]:
        rows = data.indicators_by_tf.get(tf)
        if not rows:
            raise ValueError(f"no indicator rows for timeframe={tf}")
        return rows[-1]

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _confidence(adx: float, atr_ratio: float) -> float:
        adx_term = min(max((adx - 20.0) / 20.0, 0.0), 1.0)
        atr_term = min(max((atr_ratio - 0.004) / 0.008, 0.0), 1.0)
        return min(0.55 + (0.25 * adx_term) + (0.20 * atr_term), 0.98)
