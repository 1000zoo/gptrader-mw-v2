from typing import Protocol, runtime_checkable

from src.domain.strategy.strategy_context import StrategyContext
from src.domain.strategy.strategy_result import StrategyResult


@runtime_checkable
class Strategy(Protocol):
    def evaluate(self, context: StrategyContext) -> StrategyResult:
        ...
