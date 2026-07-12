from datetime import datetime
from typing import Protocol, runtime_checkable

from src.domain.market import Symbol, Timeframe
from src.domain.market_feature import MarketFeatureSet


@runtime_checkable
class MarketFeatureProviderPort(Protocol):
    def load_features(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> MarketFeatureSet:
        ...
