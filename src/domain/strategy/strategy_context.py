from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from src.domain.indicator import IndicatorSet
from src.domain.market import MarketSnapshot
from src.domain.market_feature import MARKET_FEATURES_METADATA_KEY, MarketFeatureSet


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

        if MARKET_FEATURES_METADATA_KEY in self.metadata:
            market_features = self.metadata[MARKET_FEATURES_METADATA_KEY]
            if not isinstance(market_features, MarketFeatureSet):
                raise TypeError("market_features must be a MarketFeatureSet")
            if market_features.symbol != self.market.symbol:
                raise ValueError("market and market_features symbol must match")
            if market_features.timeframe != self.market.timeframe:
                raise ValueError("market and market_features timeframe must match")
            if market_features.measured_at != self.market.latest_candle.closed_at:
                raise ValueError(
                    "market_features measured_at must match latest candle closed_at"
                )

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def market_features(self) -> MarketFeatureSet | None:
        value = self.metadata.get(MARKET_FEATURES_METADATA_KEY)
        return value if isinstance(value, MarketFeatureSet) else None
