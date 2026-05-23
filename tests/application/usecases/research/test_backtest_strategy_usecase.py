from decimal import Decimal

from src.application.usecases.research import (
    BacktestStrategyCommand,
    BacktestStrategyUseCase,
)
from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StrategyContext, StrategyResult
from tests.domain.strategy.test_strategy_context import make_indicators, make_market


class FakeMarketData:
    def __init__(self, market):
        self.market = market
        self.requests = []

    def load_snapshot(self, symbol, timeframe, limit):
        self.requests.append((symbol, timeframe, limit))
        return self.market


class FakeStrategy:
    def __init__(self, result):
        self.result = result
        self.contexts = []

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        self.contexts.append(context)
        return self.result


def test_backtest_strategy_command_stores_research_inputs():
    market = make_market()
    indicators = make_indicators(market)

    command = BacktestStrategyCommand(
        target_id="strategy-1",
        symbol=market.symbol,
        timeframe=market.timeframe,
        candle_limit=240,
        indicators=indicators,
        metadata={"dataset": "may"},
    )

    assert command.target_id == "strategy-1"
    assert command.symbol == market.symbol
    assert command.timeframe == market.timeframe
    assert command.candle_limit == 240
    assert command.indicators == indicators
    assert command.metadata["dataset"] == "may"


def test_backtest_strategy_usecase_returns_strategy_result_and_context():
    market = make_market()
    strategy_result = StrategyResult(
        name="momentum",
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.7")),
    )
    market_data = FakeMarketData(market)
    strategy = FakeStrategy(strategy_result)
    usecase = BacktestStrategyUseCase(market_data=market_data, strategy=strategy)

    result = usecase.execute(
        BacktestStrategyCommand(
            target_id="strategy-1",
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=240,
            indicators=make_indicators(market),
            metadata={"dataset": "may"},
        )
    )

    assert result.target_id == "strategy-1"
    assert result.strategy_result == strategy_result
    assert result.context == strategy.contexts[0]
    assert result.context.metadata["dataset"] == "may"
    assert market_data.requests == [(market.symbol, market.timeframe, 240)]
