from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence


@dataclass(frozen=True)
class SignalGeneratorDefinition:
    generator_id: str
    name: str
    strategy_ids: Sequence[str]
    regime_routes: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        generator_id = self.generator_id.strip()
        name = self.name.strip()
        if not generator_id:
            raise ValueError("generator_id is required")
        if not name:
            raise ValueError("name is required")

        strategy_ids = tuple(strategy_id.strip() for strategy_id in self.strategy_ids)
        if not strategy_ids or any(not strategy_id for strategy_id in strategy_ids):
            raise ValueError("strategy_ids are required")

        regime_routes = {
            regime.strip(): strategy_id.strip()
            for regime, strategy_id in self.regime_routes.items()
        }
        if any(not regime or not strategy_id for regime, strategy_id in regime_routes.items()):
            raise ValueError("regime_routes must not contain blank values")

        unknown_strategy_ids = set(regime_routes.values()) - set(strategy_ids)
        if unknown_strategy_ids:
            raise ValueError("regime_routes must reference known strategy_ids")

        object.__setattr__(self, "generator_id", generator_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "strategy_ids", strategy_ids)
        object.__setattr__(self, "regime_routes", MappingProxyType(regime_routes))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
