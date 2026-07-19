from src.domain.signal import SignalDirection
from src.runtime import (
    RuntimeSettings,
    build_local_strategy_context,
    evaluate_local_example_strategy,
)


def test_build_local_strategy_context_has_matching_market_and_indicators() -> None:
    context = build_local_strategy_context(RuntimeSettings(symbol="ETHUSDT"))

    assert context.market.symbol.pair == "ETHUSDT"
    assert context.indicators.symbol == context.market.symbol
    assert context.indicators.measured_at == context.market.latest_candle.closed_at
    assert context.indicators.require("moving_average.period_3").value > 0


def test_evaluate_local_example_strategy_returns_domain_result() -> None:
    result = evaluate_local_example_strategy(RuntimeSettings())

    assert result.signal.direction is SignalDirection.LONG
