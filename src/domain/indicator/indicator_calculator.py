from typing import Protocol

from src.domain.indicator.indicator_set import IndicatorSet
from src.domain.market.market_snapshot import MarketSnapshot


class IndicatorCalculator(Protocol):
    def calculate(self, snapshot: MarketSnapshot) -> IndicatorSet:
        ...
