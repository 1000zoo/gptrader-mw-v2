from dataclasses import dataclass
from datetime import datetime

from src.domain.indicator.indicator_value import IndicatorValue
from src.domain.market.symbol import Symbol
from src.domain.market.timeframe import Timeframe


@dataclass(frozen=True)
class IndicatorSet:
    symbol: Symbol
    timeframe: Timeframe
    measured_at: datetime
    values: tuple[IndicatorValue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))

        value_keys = set()
        for value in self.values:
            if value.measured_at != self.measured_at:
                raise ValueError("indicator value measured_at must match set measured_at")
            if value.key in value_keys:
                raise ValueError("duplicate indicator key")
            value_keys.add(value.key)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(value.key for value in self.values))

    def get(self, key: str) -> IndicatorValue | None:
        normalized_key = IndicatorValue.normalize_key(key)
        for value in self.values:
            if value.key == normalized_key:
                return value
        return None

    def require(self, key: str) -> IndicatorValue:
        value = self.get(key)
        if value is None:
            raise KeyError(f"missing indicator: {key}")
        return value
