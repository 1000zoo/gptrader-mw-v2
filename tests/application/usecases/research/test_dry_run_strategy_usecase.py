from decimal import Decimal

from src.application.usecases.research import (
    DryRunStrategyCommand,
    DryRunStrategyUseCase,
)
from src.domain.signal import Signal, SignalDirection
from src.domain.signal_generator import GeneratedSignal
from src.domain.strategy import StrategyContext
from tests.domain.strategy.test_strategy_context import make_indicators, make_market


class FakeMarketData:
    def __init__(self, market):
        self.market = market
        self.requests = []

    def load_snapshot(self, symbol, timeframe, limit):
        self.requests.append((symbol, timeframe, limit))
        return self.market


class FakeSignalGenerator:
    def __init__(self, generated_signal):
        self.generated_signal = generated_signal
        self.contexts = []

    def generate(self, context: StrategyContext) -> GeneratedSignal:
        self.contexts.append(context)
        return self.generated_signal


def test_dry_run_strategy_usecase_returns_generated_signal_without_order_execution():
    market = make_market()
    generated_signal = GeneratedSignal(
        signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("0.6")),
    )
    market_data = FakeMarketData(market)
    signal_generator = FakeSignalGenerator(generated_signal)
    usecase = DryRunStrategyUseCase(
        market_data=market_data,
        signal_generator=signal_generator,
    )

    result = usecase.execute(
        DryRunStrategyCommand(
            target_id="generator-1",
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=make_indicators(market),
            metadata={"regime": "range"},
        )
    )

    assert result.target_id == "generator-1"
    assert result.generated_signal == generated_signal
    assert result.context == signal_generator.contexts[0]
    assert result.context.metadata["regime"] == "range"
    assert market_data.requests == [(market.symbol, market.timeframe, 120)]
