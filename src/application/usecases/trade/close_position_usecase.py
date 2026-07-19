from src.application.usecases.trade.dto import (
    ClosePositionCommand,
    ClosePositionResult,
    TradeExecutionStatus,
)
from src.domain.execution import OrderRequest
from src.domain.ports import OrderExecutionPort
from src.domain.position import PositionStatus
from src.domain.signal import SignalDirection


class ClosePositionUseCase:
    def __init__(self, order_execution: OrderExecutionPort) -> None:
        self._order_execution = order_execution

    def close(self, command: ClosePositionCommand) -> ClosePositionResult:
        if command.position.status is PositionStatus.CLOSED:
            return ClosePositionResult(
                status=TradeExecutionStatus.SKIPPED,
                reason="position_not_open",
            )

        order_result = self._order_execution.submit_order(
            OrderRequest.market(
                client_order_id=self._client_order_id(command),
                symbol=command.position.symbol,
                side=self._opposite_side(command.position.direction),
                quantity=command.position.quantity,
                reduce_only=True,
            )
        )
        return ClosePositionResult(
            status=TradeExecutionStatus.ORDER_SUBMITTED,
            order_result=order_result,
        )

    def _opposite_side(self, direction: SignalDirection) -> SignalDirection:
        if direction is SignalDirection.LONG:
            return SignalDirection.SHORT
        return SignalDirection.LONG

    def _client_order_id(self, command: ClosePositionCommand) -> str:
        return f"{command.client_order_id_prefix}-{command.position.symbol.pair}"
