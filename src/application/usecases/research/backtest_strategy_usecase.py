from src.application.usecases.research.dto import (
    BacktestStrategyCommand,
    BacktestStrategyResult,
)
from src.application.usecases.research.backtest_simulator import (
    BacktestIndicatorFactory,
    simulate_backtest,
)
from src.domain.indicator import IndicatorSet
from src.domain.market import MarketSnapshot
from src.domain.ports import MarketDataPort
from src.domain.risk import PositionSizingStrategy
from src.domain.strategy import Strategy
from src.domain.strategy.take_profit_stop_loss import TakeProfitStopLossStrategy


class BacktestStrategyUseCase:
    def __init__(
        self,
        market_data: MarketDataPort,
        strategy: Strategy,
        take_profit_stop_loss_strategy: TakeProfitStopLossStrategy | None = None,
        indicator_factory: BacktestIndicatorFactory | None = None,
        position_sizing_strategy: PositionSizingStrategy | None = None,
    ) -> None:
        self._market_data = market_data
        self._strategy = strategy
        self._take_profit_stop_loss_strategy = take_profit_stop_loss_strategy
        self._indicator_factory = indicator_factory
        self._position_sizing_strategy = position_sizing_strategy

    def execute(self, command: BacktestStrategyCommand) -> BacktestStrategyResult:
        market = self._market_data.load_snapshot(
            symbol=command.symbol,
            timeframe=command.timeframe,
            limit=command.candle_limit,
        ) if command.start_at is None else MarketSnapshot(
            self._market_data.load_candles_between(
                symbol=command.symbol,
                timeframe=command.timeframe,
                start_at=command.start_at,
                end_at=command.end_at,
            )
        )
        simulation = simulate_backtest(
            command=command,
            market=market,
            strategy=self._strategy,
            indicator_factory=self._indicator_factory
            or _command_indicator_factory(command),
            take_profit_stop_loss_strategy=self._take_profit_stop_loss_strategy,
            position_sizing_strategy=self._position_sizing_strategy,
        )
        return BacktestStrategyResult(
            target_id=command.target_id,
            strategy_result=simulation.strategy_result,
            context=simulation.context,
            trades=simulation.trades,
            performance=simulation.performance,
        )


def _command_indicator_factory(
    command: BacktestStrategyCommand,
) -> BacktestIndicatorFactory:
    def build(snapshot: MarketSnapshot) -> IndicatorSet:
        if command.indicators.measured_at == snapshot.latest_candle.closed_at:
            return command.indicators
        return IndicatorSet(
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            measured_at=snapshot.latest_candle.closed_at,
            values=(),
        )

    return build
