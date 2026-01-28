import asyncio

import pytest

pydantic = pytest.importorskip("pydantic")

from src.binance.service.trader.trade_service import TradeService
from src.binance.dto.trader.trade_execute_dto import TradeExecuteDto


def test_risk_sizing_updates_percent(monkeypatch):
    monkeypatch.setenv("ENABLE_RISK_SIZING", "true")
    monkeypatch.setenv("ENABLE_RISK_ENGINE", "false")
    monkeypatch.setenv("ENABLE_KILL_SWITCH", "false")
    service = TradeService()

    async def fake_state():
        return None

    async def fake_create_trade_fill(vo):
        return 1

    service.system_state_service.find_latest_state = fake_state
    service.trade_fill_service.create_trade_fill = fake_create_trade_fill
    service.kill_switch_service.evaluate_and_update = lambda: True
    async def fake_find_latest(*args, **kwargs):
        return None

    service.signal_log_service.find_latest_by_run_id = fake_find_latest

    class DummyAccountApi:
        def get_usdt_balance(self):
            return 1000

    service.tradeApi.accountApi = DummyAccountApi()
    service.tradeApi._get_ticker_price = lambda symbol: 100
    service.tradeApi.symbolApi.get_symbol_info = lambda symbol: [{"minQty": "0.01"}]

    captured = {}

    def fake_open_market_position(**kwargs):
        captured.update(kwargs)
        return {"success": True, "main_response": {"clientOrderId": "m1"}}

    service.tradeApi.open_market_position = fake_open_market_position

    dto = TradeExecuteDto(
        symbol_id="BTCUSDT",
        side="LONG",
        entry_price=100,
        tp=105,
        sl=95,
        confidence=0.8,
        batch_id="batch-1",
        c_interval="1h",
    )

    asyncio.run(service.open_from_analyze(dto))
    assert captured["percent"] > 0
