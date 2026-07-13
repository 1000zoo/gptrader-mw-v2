from dataclasses import dataclass

from src.domain.execution.order_request import OrderRequest
from src.domain.execution.order_result import OrderResult, OrderStatus
from src.domain.position import PositionEvent


@dataclass(frozen=True)
class ExecutionReport:
    request: OrderRequest
    result: OrderResult

    def __post_init__(self) -> None:
        if self.request.client_order_id != self.result.client_order_id:
            raise ValueError("client_order_id must match request and result")

    def to_position_event(self) -> PositionEvent:
        if self.result.status not in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError("execution report must be filled")
        if self.request.reduce_only:
            raise ValueError("reduce_only report cannot create a position increase event")
        if self.result.executed_quantity is None:
            raise ValueError("executed_quantity is required")
        if self.result.average_price is None:
            raise ValueError("average_price is required")

        return PositionEvent.increase(
            direction=self.request.side,
            quantity=self.result.executed_quantity,
            price=self.result.average_price,
        )
