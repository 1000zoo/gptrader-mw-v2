from decimal import Decimal
from typing import Mapping

from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.execution.order_request import OrderType
from src.domain.market import Symbol
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


def map_binance_order_to_execution_report(
    payload: Mapping[str, object],
    symbol: Symbol,
) -> ExecutionReport:
    request = OrderRequest(
        client_order_id=str(payload["clientOrderId"]),
        symbol=symbol,
        side=_map_binance_side(str(payload["side"])),
        order_type=_map_binance_order_type(str(payload["type"])),
        quantity=Decimal(str(payload["origQty"])),
        limit_price=_optional_decimal(payload.get("price")),
        reduce_only=_map_bool(payload.get("reduceOnly", False)),
    )
    return ExecutionReport(
        request=request,
        result=map_binance_order_to_result(payload),
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


def _map_binance_side(side: str) -> SignalDirection:
    normalized_side = side.upper()
    if normalized_side == "BUY":
        return SignalDirection.LONG
    if normalized_side == "SELL":
        return SignalDirection.SHORT
    raise ValueError(f"unsupported Binance order side: {side}")


def _map_binance_order_type(order_type: str) -> OrderType:
    normalized_order_type = order_type.upper()
    if normalized_order_type == "MARKET":
        return OrderType.MARKET
    if normalized_order_type == "LIMIT":
        return OrderType.LIMIT
    raise ValueError(f"unsupported Binance order type: {order_type}")


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value)
    if not text or Decimal(text) == Decimal("0"):
        return None
    return Decimal(text)


def _map_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"
