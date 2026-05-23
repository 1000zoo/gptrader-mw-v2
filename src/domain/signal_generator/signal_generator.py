from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence, runtime_checkable

from src.domain.signal import Signal
from src.domain.strategy import StrategyContext, StrategyResult


@dataclass(frozen=True)
class GeneratedSignal:
    signal: Signal
    strategy_results: Sequence[StrategyResult] = field(default_factory=tuple)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_results", tuple(self.strategy_results))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@runtime_checkable
class SignalGenerator(Protocol):
    def generate(self, context: StrategyContext) -> GeneratedSignal:
        ...
