from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.domain.strategy.strategy import Strategy
from src.domain.strategy.strategy_spec import StrategySpec


StrategyFactory = Callable[..., Strategy]


@runtime_checkable
class StrategyCatalog(Protocol):
    def list_specs(self) -> tuple[StrategySpec, ...]:
        ...

    def create_strategy(self, spec: StrategySpec) -> Strategy:
        ...


@dataclass(frozen=True)
class StaticStrategyCatalog:
    entries: tuple[tuple[StrategySpec, StrategyFactory], ...]

    def list_specs(self) -> tuple[StrategySpec, ...]:
        return tuple(spec for spec, _factory in self.entries)

    def create_strategy(self, spec: StrategySpec) -> Strategy:
        for candidate, factory in self.entries:
            if candidate.strategy_id == spec.strategy_id:
                return factory(**dict(spec.parameters))
        raise KeyError(f"unknown strategy spec: {spec.strategy_id}")
