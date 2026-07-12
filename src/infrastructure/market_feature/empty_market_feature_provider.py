from datetime import datetime

from src.domain.market import Symbol, Timeframe
from src.domain.market_feature import MarketFeatureSet


class EmptyMarketFeatureProvider:
    def __init__(self, unavailable_sources: tuple[str, ...] = ()) -> None:
        self._unavailable_sources = tuple(unavailable_sources)

    def load_features(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> MarketFeatureSet:
        return MarketFeatureSet(
            symbol=symbol,
            timeframe=timeframe,
            measured_at=as_of,
            values=(),
            unavailable_sources=self._unavailable_sources,
        )
