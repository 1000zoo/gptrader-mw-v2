from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.application.usecases.strategy_lifecycle import (
    RunStrategyBacktestCycleCommand,
    RunStrategyBacktestCycleResult,
    RunStrategyBacktestCycleUseCase,
    StrategyBacktestCycleItem,
)
from src.application.usecases.strategy_lifecycle.run_strategy_backtest_cycle_usecase import (
    build_strategy_backtest_cycle_indicators,
)
from src.domain.indicator import IndicatorSet
from src.domain.lifecycle import StrategyLifecycleStatus
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import (
    StaticStrategyCatalog,
    StrategyContext,
    StrategyResult,
    StrategySpec,
)
from src.domain.strategy.take_profit_stop_loss import TakeProfitStopLossLevels
from src.domain.strategy.implementations import (
    LatestCloseMovingAverageStrategy,
    create_default_strategy_catalog,
)
from tests.domain.strategy.test_strategy_context import make_market


def test_run_strategy_backtest_cycle_command_stores_cycle_inputs() -> None:
    start_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    command = RunStrategyBacktestCycleCommand(
        cycle_id="cycle-20260617",
        metadata={"lookback": "recent"},
        enabled_strategy_ids=(" always-long ",),
        disabled_strategy_ids=("disabled-one",),
        start_at=start_at,
        end_at=end_at,
    )

    assert command.cycle_id == "cycle-20260617"
    assert command.metadata["lookback"] == "recent"
    assert command.enabled_strategy_ids == ("always-long",)
    assert command.disabled_strategy_ids == ("disabled-one",)
    assert command.start_at == start_at
    assert command.end_at == end_at


def test_run_strategy_backtest_cycle_result_splits_successes_and_failures() -> None:
    success = StrategyBacktestCycleItem(
        strategy_id="strategy-1",
        evaluation_id="eval-1",
        succeeded=True,
    )
    failure = StrategyBacktestCycleItem(
        strategy_id="strategy-2",
        evaluation_id=None,
        succeeded=False,
        error_type="RuntimeError",
        error_message="boom",
    )

    result = RunStrategyBacktestCycleResult(items=(success, failure))

    assert result.succeeded_count == 1
    assert result.failed_count == 1


def empty_indicator_factory(
    spec: StrategySpec,
    snapshot,
) -> IndicatorSet:
    return IndicatorSet(
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        measured_at=snapshot.latest_candle.closed_at,
        values=(),
    )


class FakeMarketData:
    def __init__(self, market) -> None:
        self.market = market
        self.requests = []

    def load_candles(self, symbol, timeframe, limit):
        self.requests.append(("candles", symbol, timeframe, limit))
        return self._market_for(symbol, timeframe).candles

    def load_snapshot(self, symbol, timeframe, limit):
        self.requests.append(("snapshot", symbol, timeframe, limit))
        return self._market_for(symbol, timeframe)

    def load_candles_between(self, symbol, timeframe, start_at, end_at):
        self.requests.append((symbol, timeframe, start_at, end_at))
        return tuple(
            candle
            for candle in self._market_for(symbol, timeframe).candles
            if start_at <= candle.opened_at < end_at
        )

    def _market_for(self, symbol, timeframe):
        if isinstance(self.market, dict):
            return self.market[(symbol, timeframe)]
        return self.market


class FakeStrategyRepository:
    def __init__(self) -> None:
        self.saved_definitions = []
        self.saved_signal_generator_definitions = []
        self.saved_evaluations = []

    def save_strategy_definition(self, definition) -> None:
        self.saved_definitions.append(definition)

    def load_strategy_definition(self, strategy_id):
        return None

    def save_signal_generator_definition(self, definition) -> None:
        self.saved_signal_generator_definitions.append(definition)

    def load_signal_generator_definition(self, generator_id):
        return None

    def save_strategy_evaluation(self, evaluation) -> None:
        self.saved_evaluations.append(evaluation)

    def list_strategy_evaluations(self, target_id):
        return tuple(
            evaluation
            for evaluation in self.saved_evaluations
            if evaluation.target_id == target_id
        )


class AlwaysLongStrategy:
    def evaluate(self, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            name="always-long",
            signal=Signal(
                direction=SignalDirection.LONG,
                confidence=Decimal("0.70"),
            ),
        )


class FailingStrategy:
    def evaluate(self, context: StrategyContext) -> StrategyResult:
        raise RuntimeError("boom")


class AlwaysWaitStrategy:
    def evaluate(self, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            name="always-wait",
            signal=Signal.wait(metadata={"reason": "steady"}),
        )


class FixedTakeProfitStopLossStrategy:
    def calculate(self, context: StrategyContext, direction: SignalDirection):
        entry = context.market.latest_candle.close_price
        return TakeProfitStopLossLevels(
            strategy_name="fixed",
            entry_price=entry,
            take_profit=entry + Decimal("10"),
            stop_loss=entry - Decimal("5"),
        )


def make_catalog_with_always_long_strategy(market) -> StaticStrategyCatalog:
    return StaticStrategyCatalog(
        entries=(
            (
                StrategySpec(
                    strategy_id="always-long",
                    name="Always Long",
                    implementation="tests.AlwaysLongStrategy",
                    version="1",
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    lookback_candle_limit=240,
                ),
                AlwaysLongStrategy,
            ),
        )
    )


def make_catalog_with_failing_and_wait_strategies(market) -> StaticStrategyCatalog:
    return StaticStrategyCatalog(
        entries=(
            (
                StrategySpec(
                    strategy_id="failing",
                    name="Failing",
                    implementation="tests.FailingStrategy",
                    version="1",
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    lookback_candle_limit=240,
                ),
                FailingStrategy,
            ),
            (
                StrategySpec(
                    strategy_id="always-wait",
                    name="Always Wait",
                    implementation="tests.AlwaysWaitStrategy",
                    version="1",
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    lookback_candle_limit=240,
                ),
                AlwaysWaitStrategy,
            ),
        )
    )


def make_default_catalog_snapshot(spec: StrategySpec) -> MarketSnapshot:
    start = datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc)
    interval = timedelta(seconds=spec.timeframe.duration_seconds)
    candles = []
    for index, close_price in enumerate(
        (Decimal("100"), Decimal("101"), Decimal("103"), Decimal("104"))
    ):
        opened_at = start + interval * index
        candles.append(
            Candle(
                symbol=spec.symbol,
                timeframe=spec.timeframe,
                opened_at=opened_at,
                closed_at=opened_at + interval,
                open_price=close_price - Decimal("1"),
                high_price=close_price + Decimal("1"),
                low_price=close_price - Decimal("2"),
                close_price=close_price,
                volume=Decimal("10") + Decimal(index),
            )
        )
    return MarketSnapshot(candles=tuple(candles))


def make_market_with_closes(close_prices: tuple[Decimal, ...]) -> MarketSnapshot:
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    start = datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc)
    candles = []
    for index, close_price in enumerate(close_prices):
        opened_at = start + timedelta(minutes=index)
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(minutes=1),
                open_price=close_price - Decimal("1"),
                high_price=close_price + Decimal("1"),
                low_price=close_price - Decimal("2"),
                close_price=close_price,
                volume=Decimal("10") + Decimal(index),
            )
        )
    return MarketSnapshot(candles=tuple(candles))


def make_backtest_cycle_market() -> MarketSnapshot:
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    start = datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc)
    values = (
        (Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100")),
        (Decimal("110"), Decimal("111"), Decimal("99"), Decimal("110")),
    )
    candles = []
    for index, (close_price, high_price, low_price, open_price) in enumerate(values):
        opened_at = start + timedelta(minutes=index)
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(minutes=1),
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=Decimal("10"),
            )
        )
    return MarketSnapshot(tuple(candles))


def make_catalog_with_period_4_moving_average_strategy(
    market,
) -> StaticStrategyCatalog:
    return StaticStrategyCatalog(
        entries=(
            (
                StrategySpec(
                    strategy_id="custom-moving-average",
                    name="Custom Moving Average",
                    implementation="src.domain.strategy.implementations.LatestCloseMovingAverageStrategy",
                    version="1",
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    lookback_candle_limit=240,
                    parameters={"indicator_key": "moving_average.period_4"},
                    indicator_keys=("moving_average.period_4",),
                ),
                LatestCloseMovingAverageStrategy,
            ),
        )
    )


def test_backtest_cycle_registers_definitions_and_saves_backtested_evaluations() -> None:
    market = make_market()
    repository = FakeStrategyRepository()
    market_data = FakeMarketData(market)
    usecase = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=market_data,
        strategy_catalog=make_catalog_with_always_long_strategy(market),
        indicator_factory=empty_indicator_factory,
    )

    result = usecase.execute(RunStrategyBacktestCycleCommand(cycle_id="cycle-1"))

    assert result.succeeded_count == 1
    assert result.failed_count == 0
    assert repository.saved_definitions[0].strategy_id == "always-long"
    assert repository.saved_evaluations[0].evaluation_id == "cycle-1:always-long:backtest"
    assert repository.saved_evaluations[0].target_id == "always-long"
    assert repository.saved_evaluations[0].status is StrategyLifecycleStatus.BACKTESTED
    assert repository.saved_evaluations[0].metrics["signal_confidence"] == Decimal("0.70")
    assert repository.saved_evaluations[0].metrics["direction_score"] == Decimal("1")
    assert repository.saved_evaluations[0].metrics["reason_count"] == Decimal("0")
    assert repository.saved_evaluations[0].metrics["trade_count"] == Decimal("1")
    assert "net_pnl" in repository.saved_evaluations[0].metrics
    assert "max_drawdown_ratio" in repository.saved_evaluations[0].metrics
    assert market_data.requests == [("snapshot", market.symbol, market.timeframe, 240)]


def test_default_strategy_catalog_backtest_cycle_succeeds_and_saves_evaluations() -> None:
    catalog = create_default_strategy_catalog()
    specs = catalog.list_specs()
    markets = {
        (spec.symbol, spec.timeframe): make_default_catalog_snapshot(spec)
        for spec in specs
    }
    repository = FakeStrategyRepository()

    result = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=FakeMarketData(markets),
        strategy_catalog=catalog,
    ).execute(RunStrategyBacktestCycleCommand(cycle_id="cycle-default"))

    expected_ids = {
        "latest-close-moving-average",
        "session-volume-profile",
        "chart-pattern",
        "tv-range-seed-s1-t1-p2-fixed",
        "live-compression-s2-sl0030-rr045-balanced",
        "live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2",
    }
    assert result.succeeded_count == len(expected_ids)
    assert result.failed_count == 0
    assert {item.strategy_id for item in result.items} == expected_ids
    assert len(repository.saved_evaluations) == len(expected_ids)
    assert {evaluation.target_id for evaluation in repository.saved_evaluations} == expected_ids
    assert {
        evaluation.evaluation_id for evaluation in repository.saved_evaluations
    } == {
        "cycle-default:latest-close-moving-average:backtest",
        "cycle-default:session-volume-profile:backtest",
        "cycle-default:chart-pattern:backtest",
        "cycle-default:tv-range-seed-s1-t1-p2-fixed:backtest",
        "cycle-default:live-compression-s2-sl0030-rr045-balanced:backtest",
        "cycle-default:live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2:backtest",
    }


def test_backtest_cycle_filters_enabled_strategy_ids() -> None:
    market = make_market()
    repository = FakeStrategyRepository()
    usecase = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=FakeMarketData(market),
        strategy_catalog=make_catalog_with_failing_and_wait_strategies(market),
        indicator_factory=empty_indicator_factory,
    )

    result = usecase.execute(
        RunStrategyBacktestCycleCommand(
            cycle_id="cycle-1",
            enabled_strategy_ids=("always-wait",),
        )
    )

    assert result.succeeded_count == 1
    assert result.failed_count == 0
    assert [item.strategy_id for item in result.items] == ["always-wait"]
    assert [definition.strategy_id for definition in repository.saved_definitions] == [
        "always-wait"
    ]


def test_backtest_cycle_loads_real_date_range_when_command_has_dates() -> None:
    market = make_market_with_closes(
        (Decimal("100"), Decimal("102"), Decimal("104"), Decimal("110"))
    )
    repository = FakeStrategyRepository()
    market_data = FakeMarketData(market)
    usecase = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=market_data,
        strategy_catalog=make_catalog_with_always_long_strategy(market),
        indicator_factory=empty_indicator_factory,
    )

    result = usecase.execute(
        RunStrategyBacktestCycleCommand(
            cycle_id="cycle-range",
            start_at=market.candles[0].opened_at,
            end_at=market.candles[-1].closed_at,
        )
    )

    assert result.succeeded_count == 1
    assert repository.saved_evaluations[0].evaluation_id == (
        "cycle-range:always-long:backtest"
    )
    assert market_data.requests == [
        (
            market.symbol,
            market.timeframe,
            market.candles[0].opened_at,
            market.candles[-1].closed_at,
        )
    ]


def test_backtest_cycle_passes_take_profit_stop_loss_strategy_to_simulation() -> None:
    market = make_backtest_cycle_market()
    repository = FakeStrategyRepository()

    result = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=FakeMarketData(market),
        strategy_catalog=make_catalog_with_always_long_strategy(market),
        indicator_factory=empty_indicator_factory,
        take_profit_stop_loss_strategy=FixedTakeProfitStopLossStrategy(),
    ).execute(RunStrategyBacktestCycleCommand(cycle_id="cycle-tpsl"))

    assert result.succeeded_count == 1
    assert repository.saved_evaluations[0].metrics["trade_count"] == Decimal("1")
    assert repository.saved_evaluations[0].metrics["winning_trade_count"] == Decimal("1")
    assert repository.saved_evaluations[0].metrics["average_trade_return"] == Decimal(
        "0.1"
    )


def test_backtest_cycle_uses_catalog_indicator_key_for_moving_average_strategy() -> None:
    market = make_market_with_closes(
        (Decimal("100"), Decimal("102"), Decimal("104"), Decimal("110"))
    )
    catalog = make_catalog_with_period_4_moving_average_strategy(market)
    spec = catalog.list_specs()[0]
    repository = FakeStrategyRepository()

    indicators = build_strategy_backtest_cycle_indicators(spec, market)
    result = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=FakeMarketData(market),
        strategy_catalog=catalog,
    ).execute(RunStrategyBacktestCycleCommand(cycle_id="cycle-1"))

    assert indicators.keys == ("moving_average.period_4",)
    assert indicators.require("moving_average.period_4").value == Decimal("104")
    assert result.succeeded_count == 1
    assert result.failed_count == 0
    assert repository.saved_evaluations[0].target_id == "custom-moving-average"


def test_backtest_cycle_continues_after_one_strategy_fails() -> None:
    market = make_market()
    repository = FakeStrategyRepository()
    usecase = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=FakeMarketData(market),
        strategy_catalog=make_catalog_with_failing_and_wait_strategies(market),
        indicator_factory=empty_indicator_factory,
    )

    result = usecase.execute(RunStrategyBacktestCycleCommand(cycle_id="cycle-1"))

    assert result.succeeded_count == 1
    assert result.failed_count == 1
    assert result.items[0].strategy_id == "failing"
    assert result.items[0].evaluation_id is None
    assert result.items[0].error_type == "RuntimeError"
    assert result.items[0].error_message == "boom"
    assert result.items[1].strategy_id == "always-wait"
    assert result.items[1].evaluation_id == "cycle-1:always-wait:backtest"
    assert [definition.strategy_id for definition in repository.saved_definitions] == [
        "failing",
        "always-wait",
    ]
    assert len(repository.saved_evaluations) == 1
    assert repository.saved_evaluations[0].target_id == "always-wait"
    assert repository.saved_evaluations[0].metrics["direction_score"] == Decimal("0")
