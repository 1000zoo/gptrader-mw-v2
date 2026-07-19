from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

from src.domain.signal import SignalDirection
from src.domain.strategy.strategy_context import StrategyContext


@dataclass(frozen=True)
class TakeProfitStopLossLevels:
    strategy_name: str
    entry_price: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_name.strip():
            raise ValueError("strategy_name is required")
        if self.entry_price <= Decimal("0"):
            raise ValueError("entry_price must be positive")
        if self.take_profit <= Decimal("0"):
            raise ValueError("take_profit must be positive")
        if self.stop_loss <= Decimal("0"):
            raise ValueError("stop_loss must be positive")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@runtime_checkable
class TakeProfitStopLossStrategy(Protocol):
    def calculate(
        self,
        context: StrategyContext,
        direction: SignalDirection,
    ) -> TakeProfitStopLossLevels:
        ...
