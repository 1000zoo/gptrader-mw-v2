import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("loguru")

from src.risk.risk_engine import RiskEngine


def test_risk_engine_daily_loss_denial(monkeypatch):
    monkeypatch.setenv("ENABLE_RISK_ENGINE", "true")
    monkeypatch.setenv("DAILY_LOSS_LIMIT_PCT", "0.01")
    engine = RiskEngine()

    class DummyAccountService:
        def get_usdt_balance(self):
            return 1000

        def get_positions(self):
            return []

    class DummyTradeFillService:
        async def find_closed_trades_since(self, since_ts):
            return [SimpleNamespace(pnl_usd=-20, r_multiple=-1.0)]

        async def find_recent_closed_trades(self, limit):
            return []

    class DummyExecutionAnomalyService:
        async def count_recent_anomalies(self, since_ts):
            return 0

    engine.account_service = DummyAccountService()
    engine.trade_fill_service = DummyTradeFillService()
    engine.execution_anomaly_service = DummyExecutionAnomalyService()

    decision = asyncio.run(engine.evaluate("BTCUSDT", leverage=2))
    assert decision.allowed is False
    assert "daily_loss_limit" in decision.reasons
