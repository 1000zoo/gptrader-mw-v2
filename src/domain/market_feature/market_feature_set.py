from dataclasses import dataclass
from datetime import datetime

from src.domain.market import Symbol, Timeframe
from src.domain.market_feature.market_feature_value import (
    MarketFeatureValue,
    as_utc,
    require_aware_datetime,
)


@dataclass(frozen=True)
class MarketFeatureSet:
    symbol: Symbol
    timeframe: Timeframe
    measured_at: datetime
    values: tuple[MarketFeatureValue, ...]
    unavailable_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, Symbol):
            raise TypeError("symbol must be a Symbol")
        if not isinstance(self.timeframe, Timeframe):
            raise TypeError("timeframe must be a Timeframe")
        require_aware_datetime(self.measured_at, "measured_at")

        values = tuple(self.values)
        if any(not isinstance(value, MarketFeatureValue) for value in values):
            raise TypeError("values must contain only MarketFeatureValue instances")

        if isinstance(self.unavailable_sources, str):
            raise TypeError("unavailable_sources must be an iterable of str")
        unavailable_sources = tuple(self.unavailable_sources)
        if any(not isinstance(source, str) for source in unavailable_sources):
            raise TypeError("unavailable_sources must contain only str instances")
        if any(not source.strip() for source in unavailable_sources):
            raise ValueError("unavailable source names are required")
        unavailable_sources = tuple(
            MarketFeatureValue.normalize_source(source)
            for source in unavailable_sources
        )

        feature_names = tuple(value.name for value in values)
        if len(feature_names) != len(set(feature_names)):
            raise ValueError("duplicate feature name")
        if len(unavailable_sources) != len(set(unavailable_sources)):
            raise ValueError("duplicate unavailable source")
        measured_at_utc = as_utc(self.measured_at)
        if any(as_utc(value.available_at) > measured_at_utc for value in values):
            raise ValueError("feature available_at must be before or equal to measured_at")

        available_sources = {value.source for value in values}
        if available_sources.intersection(unavailable_sources):
            raise ValueError("source cannot be both available and unavailable")

        object.__setattr__(self, "values", values)
        object.__setattr__(self, "unavailable_sources", unavailable_sources)

    def get(self, name: str) -> MarketFeatureValue | None:
        normalized_name = MarketFeatureValue.normalize_name(name)
        return next(
            (value for value in self.values if value.name == normalized_name),
            None,
        )

    def require(self, name: str) -> MarketFeatureValue:
        value = self.get(name)
        if value is None:
            raise KeyError(f"missing market feature: {name}")
        return value
