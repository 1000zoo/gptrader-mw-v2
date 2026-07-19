from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.strategy.strategies.models import TF, StrategyDecision, StrategyInitConfig, StrategyRunInput


class IStrategy(ABC):
    def __init__(self):
        self._initialized: bool = False
        self._config: Optional[StrategyInitConfig] = None

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

            ohlcv = data.ohlcv_by_tf.get(tf)
            if ohlcv is None:
                raise ValueError(f"missing timeframe ohlcv: {tf}")

            min_rows = self._config.lookback_by_tf[tf]
            if len(rows) < min_rows:
                raise ValueError(
                    f"insufficient rows for {tf}: need={min_rows}, got={len(rows)}"
                )

    def _latest(self, data: StrategyRunInput, tf: TF, col: str) -> Any:
        rows = data.indicators_by_tf.get(tf)
        if not rows:
            raise ValueError(f"no indicator rows for timeframe={tf}")
        if col not in rows[-1]:
            raise ValueError(f"indicator column not found: {col}")
        return rows[-1][col]

    def _window(self, data: StrategyRunInput, tf: TF, n: int) -> List[Dict[str, Any]]:
        rows = data.indicators_by_tf.get(tf)
        if rows is None:
            raise ValueError(f"missing timeframe indicators: {tf}")
        if n < 1:
            raise ValueError("window size must be >= 1")
        return rows[-n:]

    def _hold(self, reason: str, metadata: Optional[Dict[str, Any]] = None) -> StrategyDecision:
        return StrategyDecision(action="HOLD", confidence=0.0, reason=reason, metadata=metadata or {})

    def name(self) -> str:
        if self._config is None:
            return self.__class__.__name__
        return self._config.strategy_name

    @abstractmethod
    def run_strategy(self, data: StrategyRunInput) -> StrategyDecision:
        ...

    @abstractmethod
    def run_exit_strategy(self, data: StrategyRunInput) -> StrategyDecision:
        ...

    @property
    def limit_config(self):
        return self._config.limit

    @property
    def params_id(self):
        return self._config.params_id
