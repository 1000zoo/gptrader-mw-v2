from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from src.domain.indicator import IndicatorSet
from src.domain.market import MarketSnapshot


@dataclass(frozen=True)
class StrategyContext:
    market: MarketSnapshot
    indicators: IndicatorSet
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.market.symbol != self.indicators.symbol:
            raise ValueError("market and indicators symbol must match")
        if self.market.timeframe != self.indicators.timeframe:
            raise ValueError("market and indicators timeframe must match")
        if self.market.latest_candle.closed_at != self.indicators.measured_at:
            raise ValueError("indicators measured_at must match latest candle closed_at")

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
