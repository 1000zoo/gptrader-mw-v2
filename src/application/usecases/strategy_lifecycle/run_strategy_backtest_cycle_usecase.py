from collections.abc import Callable
from decimal import Decimal

from src.application.usecases.research import (
    BacktestStrategyCommand,
    BacktestStrategyUseCase,
    EvaluateStrategyCommand,
    EvaluateStrategyUseCase,
    ResearchRunMode,
)
from src.application.usecases.strategy_lifecycle.dto import (
    RunStrategyBacktestCycleCommand,
    RunStrategyBacktestCycleResult,
    StrategyBacktestCycleItem,
)
from src.domain.indicator import IndicatorSet, IndicatorValue
from src.domain.lifecycle import StrategyDefinition
from src.domain.market import MarketSnapshot
from src.domain.ports import MarketDataPort, StrategyRepositoryPort
from src.domain.risk import PositionSizingStrategy
from src.domain.signal import SignalDirection
from src.domain.strategy import (
    StrategyCatalog,
    StrategySpec,
    TakeProfitStopLossStrategy,
)


IndicatorFactory = Callable[[StrategySpec, MarketSnapshot], IndicatorSet]


class RunStrategyBacktestCycleUseCase:
    def __init__(
        self,
        strategy_repository: StrategyRepositoryPort,
        market_data: MarketDataPort,
        strategy_catalog: StrategyCatalog,
        indicator_factory: IndicatorFactory | None = None,
        take_profit_stop_loss_strategy: TakeProfitStopLossStrategy | None = None,
        position_sizing_strategy: PositionSizingStrategy | None = None,
    ) -> None:
        self._strategy_repository = strategy_repository
        self._market_data = market_data
        self._strategy_catalog = strategy_catalog
        self._take_profit_stop_loss_strategy = take_profit_stop_loss_strategy
        self._position_sizing_strategy = position_sizing_strategy
        self._indicator_factory = (
            indicator_factory or build_strategy_backtest_cycle_indicators
        )
        self._evaluate_strategy = EvaluateStrategyUseCase()

    def execute(
        self,
        command: RunStrategyBacktestCycleCommand,
    ) -> RunStrategyBacktestCycleResult:
        items: list[StrategyBacktestCycleItem] = []
        for spec in self._selected_specs(command):
            self._strategy_repository.save_strategy_definition(
                _definition_from_spec(spec)
            )
            try:
                item, evaluation = self._run_one(command, spec)
            except Exception as exc:
                items.append(
                    StrategyBacktestCycleItem(
                        strategy_id=spec.strategy_id,
                        evaluation_id=None,
                        succeeded=False,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
                continue

            self._strategy_repository.save_strategy_evaluation(evaluation)
            items.append(item)

        return RunStrategyBacktestCycleResult(items=tuple(items))

    def _selected_specs(
        self,
        command: RunStrategyBacktestCycleCommand,
    ) -> tuple[StrategySpec, ...]:
        specs = self._strategy_catalog.list_specs()
        if command.enabled_strategy_ids:
            enabled = set(command.enabled_strategy_ids)
            specs = tuple(spec for spec in specs if spec.strategy_id in enabled)
        if command.disabled_strategy_ids:
            disabled = set(command.disabled_strategy_ids)
            specs = tuple(spec for spec in specs if spec.strategy_id not in disabled)
        return specs

    def _run_one(
        self,
        command: RunStrategyBacktestCycleCommand,
        spec: StrategySpec,
    ):
        snapshot = self._load_market(command, spec)
        strategy = self._strategy_catalog.create_strategy(spec)
        indicators = self._indicator_factory(spec, snapshot)
        backtest = BacktestStrategyUseCase(
            market_data=_SnapshotMarketData(snapshot),
            strategy=strategy,
            indicator_factory=lambda rolling_snapshot: self._indicator_factory(
                spec,
                rolling_snapshot,
            ),
            take_profit_stop_loss_strategy=self._take_profit_stop_loss_strategy,
            position_sizing_strategy=self._position_sizing_strategy,
        ).execute(
            BacktestStrategyCommand(
                target_id=spec.strategy_id,
                symbol=spec.symbol,
                timeframe=spec.timeframe,
                candle_limit=spec.lookback_candle_limit,
                indicators=indicators,
                metadata={
                    **dict(command.metadata),
                    "cycle_id": command.cycle_id,
                    "strategy_version": spec.version,
                },
            )
        )
        evaluation_id = f"{command.cycle_id}:{spec.strategy_id}:backtest"
        evaluation = self._evaluate_strategy.execute(
            EvaluateStrategyCommand(
                evaluation_id=evaluation_id,
                target_id=spec.strategy_id,
                mode=ResearchRunMode.BACKTEST,
                metrics=_metrics_from_backtest(backtest),
                metadata={
                    **dict(command.metadata),
                    "cycle_id": command.cycle_id,
                    "strategy_name": spec.name,
                    "strategy_version": spec.version,
                    "signal_direction": backtest.strategy_result.signal.direction.value,
                },
            )
        ).evaluation
        return (
            StrategyBacktestCycleItem(
                strategy_id=spec.strategy_id,
                evaluation_id=evaluation_id,
                succeeded=True,
            ),
            evaluation,
        )

    def _load_market(
        self,
        command: RunStrategyBacktestCycleCommand,
        spec: StrategySpec,
    ) -> MarketSnapshot:
        if command.start_at is not None and command.end_at is not None:
            return MarketSnapshot(
                self._market_data.load_candles_between(
                    symbol=spec.symbol,
                    timeframe=spec.timeframe,
                    start_at=command.start_at,
                    end_at=command.end_at,
                )
            )
        return self._market_data.load_snapshot(
            symbol=spec.symbol,
            timeframe=spec.timeframe,
            limit=spec.lookback_candle_limit,
        )


def build_strategy_backtest_cycle_indicators(
    spec: StrategySpec,
    snapshot: MarketSnapshot,
) -> IndicatorSet:
    measured_at = snapshot.latest_candle.closed_at
    values: list[IndicatorValue] = []
    for indicator_key in spec.indicator_keys:
        moving_average_period = _moving_average_period_from_key(indicator_key)
        if moving_average_period is None:
            continue
        if len(snapshot.candles) < moving_average_period:
            continue

        closes = [
            candle.close_price for candle in snapshot.candles[-moving_average_period:]
        ]
        values.append(
            IndicatorValue(
                name="moving_average",
                value=sum(closes, Decimal("0")) / Decimal(moving_average_period),
                measured_at=measured_at,
                parameters={"period": moving_average_period},
            )
        )
    return IndicatorSet(
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        measured_at=measured_at,
        values=tuple(values),
    )


def _moving_average_period_from_key(indicator_key: str) -> int | None:
    prefix = "moving_average.period_"
    if not indicator_key.startswith(prefix):
        return None

    period_text = indicator_key.removeprefix(prefix)
    if not period_text.isdecimal():
        return None

    period = int(period_text)
    if period <= 0:
        return None
    return period


def _definition_from_spec(spec: StrategySpec) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id=spec.strategy_id,
        name=spec.name,
        implementation=spec.implementation,
        version=spec.version,
        parameters=spec.parameters,
        metadata=spec.metadata,
    )


def _metrics_from_result(strategy_result) -> dict[str, Decimal]:
    metrics = {
        "signal_confidence": strategy_result.signal.confidence,
        "direction_score": (
            Decimal("0")
            if strategy_result.signal.direction is SignalDirection.WAIT
            else Decimal("1")
        ),
        "reason_count": Decimal(len(strategy_result.signal.reasons)),
    }
    return metrics


def _metrics_from_backtest(backtest) -> dict[str, Decimal]:
    metrics = _metrics_from_result(backtest.strategy_result)
    performance = backtest.performance
    if performance is None:
        return metrics
    metrics.update(
        {
            "initial_equity": performance.initial_equity,
            "final_equity": performance.final_equity,
            "net_pnl": performance.net_pnl,
            "return_ratio": performance.return_ratio,
            "max_drawdown_ratio": performance.max_drawdown_ratio,
            "trade_count": Decimal(performance.trade_count),
            "winning_trade_count": Decimal(performance.winning_trade_count),
            "losing_trade_count": Decimal(performance.losing_trade_count),
            "win_rate": performance.win_rate,
            "average_trade_return": _average_trade_return(backtest.trades),
        }
    )
    return metrics


def _average_trade_return(trades) -> Decimal:
    if not trades:
        return Decimal("0")
    returns = []
    for trade in trades:
        notional = trade.entry_price * trade.quantity
        if notional <= Decimal("0"):
            continue
        returns.append(trade.net_pnl / notional)
    if not returns:
        return Decimal("0")
    return sum(returns, Decimal("0")) / Decimal(len(returns))


class _SnapshotMarketData:
    def __init__(self, snapshot: MarketSnapshot) -> None:
        self._snapshot = snapshot

    def load_candles(self, symbol, timeframe, limit):
        return self._snapshot.candles

    def load_snapshot(self, symbol, timeframe, limit) -> MarketSnapshot:
        return self._snapshot
