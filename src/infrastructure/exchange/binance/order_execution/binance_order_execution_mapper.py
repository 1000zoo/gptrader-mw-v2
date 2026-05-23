from decimal import Decimal
from typing import Mapping

from src.domain.execution import OrderRequest, OrderResult
from src.domain.execution.order_request import OrderType
from src.domain.signal import SignalDirection


def map_order_request_to_binance_params(request: OrderRequest) -> dict[str, object]:
    params: dict[str, object] = {
        "symbol": request.symbol.pair,
        "side": _map_side(request.side),
        "type": _map_order_type(request.order_type),
        "quantity": str(request.quantity),
        "newClientOrderId": request.client_order_id,
        "reduceOnly": request.reduce_only,
    }
    if request.limit_price is not None:
        params["price"] = str(request.limit_price)
    return params


def map_binance_order_to_result(payload: Mapping[str, object]) -> OrderResult:
    status = str(payload["status"]).upper()
    client_order_id = str(payload["clientOrderId"])
    exchange_order_id = str(payload["orderId"])

    if status == "FILLED":
        return OrderResult.filled(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            executed_quantity=Decimal(str(payload["executedQty"])),
            average_price=Decimal(str(payload["avgPrice"])),
        )
    if status == "PARTIALLY_FILLED":
        return OrderResult.partially_filled(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            executed_quantity=Decimal(str(payload["executedQty"])),
            average_price=Decimal(str(payload["avgPrice"])),
        )
    if status in {"NEW", "PENDING_NEW"}:
        return OrderResult.accepted(client_order_id, exchange_order_id)
    if status in {"CANCELED", "EXPIRED"}:
        return OrderResult.canceled(client_order_id, exchange_order_id)
    if status == "REJECTED":
        return OrderResult.rejected(
            client_order_id=client_order_id,
            failure_reason=str(payload.get("rejectReason", "order rejected")),
        )

    return OrderResult.rejected(
        client_order_id=client_order_id,
        failure_reason=f"unsupported Binance order status: {status}",
    )


def _map_side(side: SignalDirection) -> str:
    if side is SignalDirection.LONG:
        return "BUY"
    if side is SignalDirection.SHORT:
        return "SELL"
    raise ValueError("order side must be LONG or SHORT")


def _map_order_type(order_type: OrderType) -> str:
    if order_type is OrderType.MARKET:
        return "MARKET"
    if order_type is OrderType.LIMIT:
        return "LIMIT"
    raise ValueError(f"unsupported order type: {order_type}")
