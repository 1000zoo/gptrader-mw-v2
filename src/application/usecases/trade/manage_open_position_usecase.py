from src.application.usecases.trade.close_position_usecase import ClosePositionUseCase
from src.application.usecases.trade.dto import (
    ClosePositionCommand,
    ManageOpenPositionCommand,
    ManageOpenPositionResult,
    TradeExecutionStatus,
)
from src.domain.ports import MarketDataPort, SignalLogEntry, SignalLogRepositoryPort
from src.domain.position import PositionStatus
from src.domain.signal import SignalDirection
from src.domain.signal_generator import SignalGenerator
from src.domain.strategy import StrategyContext
from src.observability.logging import runtime_logger


class ManageOpenPositionUseCase:
    def __init__(
        self,
        market_data: MarketDataPort,
        signal_generator: SignalGenerator,
        signal_log_repository: SignalLogRepositoryPort,
        close_position_usecase: ClosePositionUseCase,
    ) -> None:
        self._market_data = market_data
        self._signal_generator = signal_generator
        self._signal_log_repository = signal_log_repository
        self._close_position_usecase = close_position_usecase

    def manage(self, command: ManageOpenPositionCommand) -> ManageOpenPositionResult:
        if command.position.status is PositionStatus.CLOSED:
            return ManageOpenPositionResult(
                status=TradeExecutionStatus.SKIPPED,
                reason="position_not_open",
            )

        market = self._market_data.load_snapshot(
            symbol=command.position.symbol,
            timeframe=command.timeframe,
            limit=command.candle_limit,
        )
        context = StrategyContext(market=market, indicators=command.indicators)
        generated_signal = self._signal_generator.generate(context)
        self._signal_log_repository.append_signal(
            SignalLogEntry(
                signal_id=command.signal_id,
                generator_id=command.generator_id,
                generated_signal=generated_signal,
            )
        )

        if not _is_opposite_signal(
            position_direction=command.position.direction,
            signal_direction=generated_signal.signal.direction,
        ):
            return ManageOpenPositionResult(
                status=TradeExecutionStatus.SKIPPED,
                generated_signal=generated_signal,
                reason="position_signal_still_valid",
            )

        runtime_logger.info(
            "open position exit triggered",
            signal_id=command.signal_id,
            symbol=command.position.symbol.pair,
            position_direction=command.position.direction.value,
            signal_direction=generated_signal.signal.direction.value,
            reason="opposite_signal",
        )
        close_result = self._close_position_usecase.close(
            ClosePositionCommand(
                position=command.position,
                client_order_id_prefix=command.client_order_id_prefix,
            )
        )
        return ManageOpenPositionResult(
            status=close_result.status,
            generated_signal=generated_signal,
            close_result=close_result,
            reason="opposite_signal",
        )


def _is_opposite_signal(
    position_direction: SignalDirection,
    signal_direction: SignalDirection,
) -> bool:
    return (
        position_direction is SignalDirection.LONG
        and signal_direction is SignalDirection.SHORT
    ) or (
        position_direction is SignalDirection.SHORT
        and signal_direction is SignalDirection.LONG
    )
