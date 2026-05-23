from decimal import Decimal

from src.domain.execution import OrderRequest, OrderResult
from src.domain.market import Symbol
from src.domain.ports import OrderExecutionPort
from src.domain.signal import SignalDirection
from src.infrastructure.exchange.binance.order_execution import BinanceOrderExecutionAdapter


class FakeBinanceOrderClient:
    def __init__(self) -> None:
        self.orders = []

    def create_order(self, **params):
        self.orders.append(params)
        return {
            "clientOrderId": params["newClientOrderId"],
            "orderId": 12345,
            "status": "FILLED",
            "executedQty": "0.25",
            "avgPrice": "42000.5",
        }


def test_binance_order_execution_adapter_submits_domain_market_order():
    client = FakeBinanceOrderClient()
    adapter = BinanceOrderExecutionAdapter(client)

    result = adapter.submit_order(
        OrderRequest.market(
            client_order_id="entry-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.LONG,
            quantity=Decimal("0.25"),
        )
    )

    assert isinstance(adapter, OrderExecutionPort)
    assert client.orders == [
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": "0.25",
            "newClientOrderId": "entry-1",
            "reduceOnly": False,
        }
    ]
    assert result == OrderResult.filled(
        client_order_id="entry-1",
        exchange_order_id="12345",
        executed_quantity=Decimal("0.25"),
        average_price=Decimal("42000.5"),
    )
