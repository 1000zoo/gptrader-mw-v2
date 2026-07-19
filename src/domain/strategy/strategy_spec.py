from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from src.domain.market import Symbol, Timeframe


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    name: str
    implementation: str
    version: str
    symbol: Symbol
    timeframe: Timeframe
    lookback_candle_limit: int
    parameters: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)
    indicator_keys: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        strategy_id = self.strategy_id.strip()
        name = self.name.strip()
        implementation = self.implementation.strip()
        version = self.version.strip()

        if not strategy_id:
            raise ValueError("strategy_id is required")
        if not name:
            raise ValueError("name is required")
        if not implementation:
            raise ValueError("implementation is required")
        if not version:
            raise ValueError("version is required")
        if self.lookback_candle_limit <= 0:
            raise ValueError("lookback_candle_limit must be positive")

        indicator_keys = tuple(
            str(indicator_key).strip().lower().replace(" ", "_")
            for indicator_key in self.indicator_keys
        )
        if any(not indicator_key for indicator_key in indicator_keys):
            raise ValueError("indicator_keys are required")
        if len(set(indicator_keys)) != len(indicator_keys):
            raise ValueError("indicator_keys must be unique")

        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "implementation", implementation)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "indicator_keys", indicator_keys)
