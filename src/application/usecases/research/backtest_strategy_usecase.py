from src.application.usecases.research.dto import (
    BacktestStrategyCommand,
    BacktestStrategyResult,
)
from src.domain.ports import MarketDataPort
from src.domain.strategy import Strategy, StrategyContext


class BacktestStrategyUseCase:
    def __init__(self, market_data: MarketDataPort, strategy: Strategy) -> None:
        self._market_data = market_data
        self._strategy = strategy

    def execute(self, command: BacktestStrategyCommand) -> BacktestStrategyResult:
        market = self._market_data.load_snapshot(
            symbol=command.symbol,
            timeframe=command.timeframe,
            limit=command.candle_limit,
        )
        context = StrategyContext(
            market=market,
            indicators=command.indicators,
            metadata=command.metadata,
        )
        strategy_result = self._strategy.evaluate(context)

        return BacktestStrategyResult(
            target_id=command.target_id,
            strategy_result=strategy_result,
            context=context,
        )
