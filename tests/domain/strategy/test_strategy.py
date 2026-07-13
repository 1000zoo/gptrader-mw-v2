from decimal import Decimal
from typing import Protocol

from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import Strategy, StrategyContext, StrategyResult
from tests.domain.strategy.test_strategy_context import make_indicators, make_market


class AlwaysLongStrategy:
    def evaluate(self, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            name="always_long",
            signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.6")),
        )


def test_strategy_is_protocol_contract():
    assert issubclass(Strategy, Protocol)


def test_strategy_accepts_implementations_with_evaluate_method():
    market = make_market()
    context = StrategyContext(market=market, indicators=make_indicators(market))
    strategy = AlwaysLongStrategy()

    result = strategy.evaluate(context)

    assert isinstance(strategy, Strategy)
    assert result.name == "always_long"
    assert result.signal.direction == SignalDirection.LONG
