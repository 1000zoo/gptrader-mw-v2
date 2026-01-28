import asyncio

import pytest

pytest.importorskip("loguru")

from src.binance.ws.handler.handler.order_event_handler import OrderEventHandler


def test_order_event_handler_records_anomaly(monkeypatch):
    handler = OrderEventHandler()
    recorded = {}

    async def fake_create(vo):
        recorded["anomaly"] = vo
        return 1

    handler.execution_anomaly_service.create_execution_anomaly = fake_create

    asyncio.run(
        handler._record_anomaly(
            batch_id="batch-1",
            symbol_id="BTCUSDT",
            anomaly_type="SLIPPAGE",
            severity="HIGH",
            trade_fill_id=1,
            signal_log_id=2,
            order_id="o1",
            payload={"fill": 100},
        )
    )

    assert recorded["anomaly"].anomaly_type == "SLIPPAGE"
