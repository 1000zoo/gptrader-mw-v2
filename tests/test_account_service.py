import asyncio

from src.binance.service.trader.account_service import AccountService
from src.binance.vo.trader.account_position_default import DefaultAccountPositionVo
from src.risk.risk_engine import RiskEngine


class _DummyApi:
    def get_current_positions(self):
        return [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.001",
                "entryPrice": "66000.1",
                "breakEvenPrice": "66010.0",
                "markPrice": "66100.5",
                "unRealizedProfit": "0.1",
                "liquidationPrice": "50000",
                "leverage": "10",
                "maxNotionalValue": "1000000",
                "marginType": "cross",
                "isolatedMargin": "0.0",
                "isAutoAddMargin": "false",
                "positionSide": "BOTH",
                "notional": "66.1",
                "isolatedWallet": "0",
                "updateTime": 1700000000000,
                "bidNotional": "0",
                "askNotional": "0",
            }
        ]


def test_account_service_get_positions_returns_vo_list():
    svc = AccountService()
    svc.api = _DummyApi()

    positions = svc.get_positions()

    assert len(positions) == 1
    assert isinstance(positions[0], DefaultAccountPositionVo)
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].position_amt == 0.001
    assert positions[0].entry_price == 66000.1
    assert positions[0].leverage == 10


def test_risk_engine_accepts_position_vo():
    class DummyAccountService:
        def get_usdt_balance(self):
            return 1000.0

        def get_positions(self):
            return [
                DefaultAccountPositionVo(
                    symbol="BTCUSDT",
                    position_amt=1.0,
                    entry_price=100.0,
                )
            ]

    class DummyTradeFillService:
        async def find_closed_trades_since(self, since_ts):
            return []

        async def find_recent_closed_trades(self, limit):
            return []

    class DummyExecutionAnomalyService:
        async def count_recent_anomalies(self, since_ts):
            return 0

    engine = RiskEngine()
    engine.enabled = True
    engine.max_open_positions = 1
    engine.account_service = DummyAccountService()
    engine.trade_fill_service = DummyTradeFillService()
    engine.execution_anomaly_service = DummyExecutionAnomalyService()

    decision = asyncio.run(engine.evaluate("BTCUSDT", leverage=2))

    assert decision.allowed is False
    assert "max_open_positions" in decision.reasons
