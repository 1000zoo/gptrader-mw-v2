from decimal import Decimal

from src.domain.signal import Signal, SignalDirection
from src.domain.signal_generator import GeneratedSignal, RegimeSignalGenerator
from src.domain.strategy import StrategyContext
from tests.domain.strategy.test_strategy_context import make_indicators, make_market


class StaticGenerator:
    def __init__(self, direction: SignalDirection) -> None:
        self.direction = direction

    def generate(self, context: StrategyContext) -> GeneratedSignal:
        return GeneratedSignal(
            signal=Signal(direction=self.direction, confidence=Decimal("0.9")),
        )


def make_context(regime: object | None = None) -> StrategyContext:
    market = make_market()
    metadata = {} if regime is None else {"regime": regime}
    return StrategyContext(
        market=market,
        indicators=make_indicators(market),
        metadata=metadata,
    )


def test_regime_signal_generator_delegates_to_matching_regime_generator():
    generator = RegimeSignalGenerator(
        generators={"trend": StaticGenerator(SignalDirection.LONG)}
    )

    generated = generator.generate(make_context("trend"))

    assert generated.signal.direction is SignalDirection.LONG
    assert generated.signal.confidence == Decimal("0.9")


def test_regime_signal_generator_returns_wait_for_missing_regime():
    generator = RegimeSignalGenerator(
        generators={"trend": StaticGenerator(SignalDirection.LONG)}
    )

    generated = generator.generate(make_context())

    assert generated.signal.direction is SignalDirection.WAIT


def test_regime_signal_generator_returns_wait_for_unknown_regime():
    generator = RegimeSignalGenerator(
        generators={"trend": StaticGenerator(SignalDirection.LONG)}
    )

    generated = generator.generate(make_context("range"))

    assert generated.signal.direction is SignalDirection.WAIT
