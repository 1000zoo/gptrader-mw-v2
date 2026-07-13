from src.application.usecases.research.dto import (
    DryRunStrategyCommand,
    DryRunStrategyResult,
)
from src.domain.ports import MarketDataPort
from src.domain.signal_generator import SignalGenerator
from src.domain.strategy import StrategyContext


class DryRunStrategyUseCase:
    def __init__(
        self,
        market_data: MarketDataPort,
        signal_generator: SignalGenerator,
    ) -> None:
        self._market_data = market_data
        self._signal_generator = signal_generator

    def execute(self, command: DryRunStrategyCommand) -> DryRunStrategyResult:
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
        generated_signal = self._signal_generator.generate(context)

        return DryRunStrategyResult(
            target_id=command.target_id,
            generated_signal=generated_signal,
            context=context,
        )
