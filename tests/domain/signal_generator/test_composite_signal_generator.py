from decimal import Decimal

import pytest

from src.domain.signal import Signal, SignalDirection
from src.domain.signal_generator import CompositeSignalGenerator
from src.domain.strategy import StrategyContext, StrategyResult
from tests.domain.strategy.test_strategy_context import make_indicators, make_market


class StaticStrategy:
    def __init__(self, name: str, direction: SignalDirection, confidence: str) -> None:
        self.name = name
        self.direction = direction
        self.confidence = Decimal(confidence)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            name=self.name,
            signal=Signal(direction=self.direction, confidence=self.confidence),
        )


def make_context() -> StrategyContext:
    market = make_market()
    return StrategyContext(market=market, indicators=make_indicators(market))


def test_composite_signal_generator_rejects_empty_strategy_list():
    with pytest.raises(ValueError, match="strategies"):
        CompositeSignalGenerator(strategies=())


def test_composite_signal_generator_chooses_highest_confidence_direction():
    generator = CompositeSignalGenerator(
        strategies=(
            StaticStrategy("breakout", SignalDirection.LONG, "0.8"),
            StaticStrategy("pullback", SignalDirection.LONG, "0.6"),
            StaticStrategy("mean_reversion", SignalDirection.SHORT, "0.7"),
        )
    )

    generated = generator.generate(make_context())

    assert generated.signal.direction is SignalDirection.LONG
    assert generated.signal.confidence == Decimal("0.7")
    assert [result.name for result in generated.strategy_results] == [
        "breakout",
        "pullback",
        "mean_reversion",
    ]


def test_composite_signal_generator_returns_wait_when_direction_scores_tie():
    generator = CompositeSignalGenerator(
        strategies=(
            StaticStrategy("long", SignalDirection.LONG, "0.7"),
            StaticStrategy("short", SignalDirection.SHORT, "0.7"),
        )
    )

    generated = generator.generate(make_context())

    assert generated.signal.direction is SignalDirection.WAIT
    assert generated.signal.confidence == Decimal("0")


def test_composite_signal_generator_returns_wait_when_all_strategies_wait():
    generator = CompositeSignalGenerator(
        strategies=(
            StaticStrategy("flat", SignalDirection.WAIT, "0"),
            StaticStrategy("quiet", SignalDirection.WAIT, "0"),
        )
    )

    generated = generator.generate(make_context())

    assert generated.signal.direction is SignalDirection.WAIT
    assert generated.signal.confidence == Decimal("0")
