from decimal import Decimal

from src.domain.ports import AccountPort, AccountSnapshot, AssetBalance
from src.infrastructure.exchange.binance.account import binance_account_adapter
from src.infrastructure.exchange.binance.account import BinanceAccountAdapter
from src.infrastructure.exchange.binance.binance_config import BinanceConfig


def _futures_account_payload():
    return {
        "totalWalletBalance": "1200.50",
        "totalMarginBalance": "1215.75",
        "assets": [
            {
                "asset": "USDT",
                "walletBalance": "1000.25",
                "availableBalance": "870.25",
                "initialMargin": "75",
                "openOrderInitialMargin": "25",
                "positionInitialMargin": "50",
                "maintMargin": "12.5",
            },
            {
                "asset": "BTC",
                "walletBalance": "0.10",
                "availableBalance": "0.04",
                "initialMargin": "0.06",
                "openOrderInitialMargin": "0.01",
                "positionInitialMargin": "0.05",
                "maintMargin": "0",
            },
            {
                "asset": "ETH",
                "walletBalance": "0",
                "availableBalance": "0",
                "initialMargin": "0",
                "openOrderInitialMargin": "0",
                "positionInitialMargin": "0",
                "maintMargin": "0",
            },
        ],
    }


def test_binance_account_adapter_loads_domain_account_snapshot(monkeypatch):
    config = BinanceConfig.default()
    requests = []

    def fake_load_account_api(received_config: BinanceConfig):
        requests.append(received_config)
        return _futures_account_payload()

    monkeypatch.setattr(
        binance_account_adapter,
        "load_account_api",
        fake_load_account_api,
    )
    adapter = BinanceAccountAdapter(config)

    snapshot = adapter.load_account_snapshot()

    assert isinstance(adapter, AccountPort)
    assert requests == [config]
    assert snapshot == AccountSnapshot(
        balances=(
            AssetBalance("USDT", free=Decimal("870.25"), locked=Decimal("75")),
            AssetBalance("BTC", free=Decimal("0.04"), locked=Decimal("0.06")),
        ),
        total_equity=Decimal("1215.75"),
    )
