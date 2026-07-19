from decimal import Decimal

from datetime import datetime, timezone

from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.market import Symbol
from src.domain.ports import OrderExecutionPort
from src.domain.signal import SignalDirection
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.order_execution import BinanceOrderExecutionAdapter
from src.infrastructure.exchange.binance.order_execution import (
    binance_order_execution_adapter,
)
from src.infrastructure.exchange.binance.order_execution.binance_order_execution_mapper import (
    map_order_request_to_binance_params,
)


def test_binance_order_execution_adapter_submits_domain_market_order(monkeypatch):
    config = BinanceConfig.default()
    orders = []

    def fake_submit_order_api(received_config: BinanceConfig, params):
        orders.append((received_config, params))
        return {
            "clientOrderId": params["newClientOrderId"],
            "orderId": 12345,
            "status": "FILLED",
            "executedQty": "0.25",
            "avgPrice": "42000.5",
        }

    monkeypatch.setattr(
        binance_order_execution_adapter,
        "submit_order_api",
        fake_submit_order_api,
    )
    adapter = BinanceOrderExecutionAdapter(config)

    result = adapter.submit_order(
        OrderRequest.market(
            client_order_id="entry-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.LONG,
            quantity=Decimal("0.25"),
        )
    )

    assert isinstance(adapter, OrderExecutionPort)
    assert orders == [
        (
            config,
            {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": "0.25",
            "newClientOrderId": "entry-1",
            },
        )
    ]
    assert result == OrderResult.filled(
        client_order_id="entry-1",
        exchange_order_id="12345",
        executed_quantity=Decimal("0.25"),
        average_price=Decimal("42000.5"),
    )


def test_binance_order_execution_adapter_loads_execution_reports(monkeypatch):
    config = BinanceConfig.default()
    report_requests = []

    def fake_load_orders_api(
        received_config: BinanceConfig,
        symbol: str,
        start_time: int,
        end_time: int,
    ):
        report_requests.append((received_config, symbol, start_time, end_time))
        return [
            {
                "clientOrderId": "entry-1",
                "orderId": 12345,
                "side": "BUY",
                "type": "MARKET",
                "origQty": "0.25",
                "executedQty": "0.25",
                "avgPrice": "42000.5",
                "status": "FILLED",
                "reduceOnly": False,
            }
        ]

    monkeypatch.setattr(
        binance_order_execution_adapter,
        "load_orders_api",
        fake_load_orders_api,
    )
    adapter = BinanceOrderExecutionAdapter(config)
    since = datetime(2026, 5, 25, 1, 2, 3, tzinfo=timezone.utc)
    until = datetime(2026, 5, 25, 2, 3, 4, tzinfo=timezone.utc)

    reports = adapter.load_execution_reports(
        symbol=Symbol("btc", "usdt"),
        since=since,
        until=until,
    )

    assert report_requests == [(config, "BTCUSDT", 1779670923000, 1779674584000)]
    assert reports == (
        ExecutionReport(
            request=OrderRequest.market(
                client_order_id="entry-1",
                symbol=Symbol("btc", "usdt"),
                side=SignalDirection.LONG,
                quantity=Decimal("0.25"),
            ),
            result=OrderResult.filled(
                client_order_id="entry-1",
                exchange_order_id="12345",
                executed_quantity=Decimal("0.25"),
                average_price=Decimal("42000.5"),
            ),
        ),
    )


def test_binance_order_mapper_adds_limit_time_in_force():
    params = map_order_request_to_binance_params(
        OrderRequest.limit(
            client_order_id="limit-1",
            symbol=Symbol("eth", "usdt"),
            side=SignalDirection.SHORT,
            quantity=Decimal("1.5"),
            limit_price=Decimal("3150.25"),
        )
    )

    assert params == {
        "symbol": "ETHUSDT",
        "side": "SELL",
        "type": "LIMIT",
        "quantity": "1.5",
        "newClientOrderId": "limit-1",
        "price": "3150.25",
        "timeInForce": "GTC",
    }


def test_binance_order_mapper_encodes_reduce_only_only_when_true():
    params = map_order_request_to_binance_params(
        OrderRequest.market(
            client_order_id="close-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.SHORT,
            quantity=Decimal("0.25"),
            reduce_only=True,
        )
    )

    assert params["reduceOnly"] == "true"


def test_binance_order_mapper_encodes_close_position_take_profit_market():
    params = map_order_request_to_binance_params(
        OrderRequest.take_profit_market(
            client_order_id="tp-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.SHORT,
            stop_price=Decimal("72000"),
        )
    )

    assert params == {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": "72000",
        "closePosition": "true",
        "newClientOrderId": "tp-1",
    }


def test_binance_order_execution_adapter_submits_take_profit_stop_loss_orders(
    monkeypatch,
):
    config = BinanceConfig.default()
    orders = []

    def fake_submit_order_api(received_config: BinanceConfig, params):
        orders.append((received_config, params))
        return {
            "clientOrderId": params["newClientOrderId"],
            "orderId": len(orders),
            "status": "NEW",
        }

    monkeypatch.setattr(
        binance_order_execution_adapter,
        "submit_order_api",
        fake_submit_order_api,
    )
    adapter = BinanceOrderExecutionAdapter(config)

    results = adapter.submit_take_profit_stop_loss_orders(
        symbol=Symbol("btc", "usdt"),
        position_direction=SignalDirection.LONG,
        take_profit=Decimal("72000"),
        stop_loss=Decimal("68000"),
        client_order_id_prefix="protect-entry-1",
    )

    assert orders == [
        (
            config,
            {
                "symbol": "BTCUSDT",
                "side": "SELL",
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": "72000",
                "closePosition": "true",
                "newClientOrderId": "protect-entry-1-tp",
            },
        ),
        (
            config,
            {
                "symbol": "BTCUSDT",
                "side": "SELL",
                "type": "STOP_MARKET",
                "stopPrice": "68000",
                "closePosition": "true",
                "newClientOrderId": "protect-entry-1-sl",
            },
        ),
    ]
    assert results == (
        OrderResult.accepted("protect-entry-1-tp", "1"),
        OrderResult.accepted("protect-entry-1-sl", "2"),
    )
