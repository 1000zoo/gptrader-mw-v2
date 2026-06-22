from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.application.usecases.research import (
    BacktestStrategyCommand,
    BacktestStrategyUseCase,
)
from src.domain.indicator import IndicatorSet
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StrategyContext, StrategyResult
from src.domain.strategy.take_profit_stop_loss import TakeProfitStopLossLevels
from tests.domain.strategy.test_strategy_context import make_indicators, make_market


class FakeMarketData:
    def __init__(self, market):
        self.market = market
        self.requests = []

    def load_snapshot(self, symbol, timeframe, limit):
        self.requests.append((symbol, timeframe, limit))
        return self.market

    def load_candles_between(self, symbol, timeframe, start_at, end_at):
        self.requests.append((symbol, timeframe, start_at, end_at))
        return tuple(
            candle
            for candle in self.market.candles
            if start_at <= candle.opened_at < end_at
        )


class FakeStrategy:
    def __init__(self, result):
        self.result = result
        self.contexts = []

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        self.contexts.append(context)
        return self.result


class FixedTakeProfitStopLossStrategy:
    def calculate(self, context: StrategyContext, direction: SignalDirection):
        entry = context.market.latest_candle.close_price
        if direction is SignalDirection.LONG:
            return TakeProfitStopLossLevels(
                strategy_name="fixed",
                entry_price=entry,
                take_profit=entry + Decimal("10"),
                stop_loss=entry - Decimal("5"),
            )
        return TakeProfitStopLossLevels(
            strategy_name="fixed",
            entry_price=entry,
            take_profit=entry - Decimal("10"),
            stop_loss=entry + Decimal("5"),
        )


def make_backtest_market() -> MarketSnapshot:
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    start = datetime(2026, 6, 23, 0, 0, tzinfo=timezone.utc)
    candles = []
    for index, values in enumerate(
        (
            ("100", "101", "99", "100"),
            ("110", "111", "99", "110"),
        )
    ):
        close, high, low, open_price = values
        opened_at = start + timedelta(minutes=index)
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(minutes=1),
                open_price=Decimal(open_price),
                high_price=Decimal(high),
                low_price=Decimal(low),
                close_price=Decimal(close),
                volume=Decimal("1"),
            )
        )
    return MarketSnapshot(candles=tuple(candles))


def empty_indicators(market: MarketSnapshot) -> IndicatorSet:
    return IndicatorSet(
        symbol=market.symbol,
        timeframe=market.timeframe,
        measured_at=market.latest_candle.closed_at,
        values=(),
    )


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
    assert command.initial_equity == Decimal("10000")
    assert command.risk_ratio == Decimal("0.01")
    assert command.leverage == Decimal("1")
    assert command.fee_rate == Decimal("0")
    assert command.slippage_rate == Decimal("0")


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


def test_backtest_strategy_usecase_simulates_trade_performance_with_tp_exit():
    market = make_backtest_market()
    strategy_result = StrategyResult(
        name="always-long",
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
    )
    usecase = BacktestStrategyUseCase(
        market_data=FakeMarketData(market),
        strategy=FakeStrategy(strategy_result),
        take_profit_stop_loss_strategy=FixedTakeProfitStopLossStrategy(),
        indicator_factory=empty_indicators,
    )

    result = usecase.execute(
        BacktestStrategyCommand(
            target_id="strategy-1",
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=2,
            indicators=empty_indicators(market),
            initial_equity=Decimal("10000"),
            risk_ratio=Decimal("0.1"),
            leverage=Decimal("1"),
        )
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.direction is SignalDirection.LONG
    assert trade.entry_price == Decimal("100")
    assert trade.exit_price == Decimal("110")
    assert trade.quantity == Decimal("10.0")
    assert trade.exit_reason == "take_profit"
    assert trade.net_pnl == Decimal("100.0")
    assert result.performance.trade_count == 1
    assert result.performance.winning_trade_count == 1
    assert result.performance.losing_trade_count == 0
    assert result.performance.win_rate == Decimal("1")
    assert result.performance.net_pnl == Decimal("100.0")
    assert result.performance.final_equity == Decimal("10100.0")
    assert result.performance.return_ratio == Decimal("0.01")


def test_backtest_strategy_usecase_loads_real_date_range_when_command_has_dates():
    market = make_backtest_market()
    market_data = FakeMarketData(market)
    strategy_result = StrategyResult(
        name="always-long",
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
    )
    usecase = BacktestStrategyUseCase(
        market_data=market_data,
        strategy=FakeStrategy(strategy_result),
        take_profit_stop_loss_strategy=FixedTakeProfitStopLossStrategy(),
        indicator_factory=empty_indicators,
    )

    result = usecase.execute(
        BacktestStrategyCommand(
            target_id="strategy-1",
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=100,
            indicators=empty_indicators(market),
            start_at=market.candles[0].opened_at,
            end_at=market.candles[-1].closed_at,
        )
    )

    assert market_data.requests == [
        (
            market.symbol,
            market.timeframe,
            market.candles[0].opened_at,
            market.candles[-1].closed_at,
        )
    ]
    assert result.performance.trade_count == 1
