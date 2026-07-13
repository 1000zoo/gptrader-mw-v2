from decimal import Decimal
from typing import Protocol

from src.domain.signal import Signal, SignalDirection
from src.domain.signal_generator import GeneratedSignal, SignalGenerator
from src.domain.strategy import StrategyContext, StrategyResult
from tests.domain.strategy.test_strategy_context import make_indicators, make_market


class StaticSignalGenerator:
    def generate(self, context: StrategyContext) -> GeneratedSignal:
        result = StrategyResult(
            name="static",
            signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.8")),
        )
        return GeneratedSignal(signal=result.signal, strategy_results=(result,))


def test_signal_generator_is_protocol_contract():
    assert issubclass(SignalGenerator, Protocol)


def test_signal_generator_accepts_implementations_with_generate_method():
    market = make_market()
    context = StrategyContext(market=market, indicators=make_indicators(market))
    generator = StaticSignalGenerator()

    generated = generator.generate(context)

    assert isinstance(generator, SignalGenerator)
    assert generated.signal.direction is SignalDirection.LONG
    assert generated.strategy_results[0].name == "static"


def test_generated_signal_defensively_copies_metadata_and_results():
    result = StrategyResult(name="wait", signal=Signal.wait())
    metadata = {"source": "test"}
    results = [result]

    generated = GeneratedSignal(
        signal=Signal.wait(),
        strategy_results=results,
        metadata=metadata,
    )
    metadata["source"] = "changed"
    results.clear()

    assert generated.strategy_results == (result,)
    assert generated.metadata["source"] == "test"
