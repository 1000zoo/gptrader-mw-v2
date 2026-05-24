from decimal import Decimal

from src.domain.ports import AccountPort, AccountSnapshot, AssetBalance
from src.infrastructure.exchange.binance.account import BinanceAccountAdapter


class FakeBinanceAccountClient:
    def __init__(self) -> None:
        self.calls = 0

    def futures_account(self):
        self.calls += 1
        return {
            "totalWalletBalance": "1200.50",
            "assets": [
                {"asset": "USDT", "walletBalance": "1000.25", "maintMargin": "12.5"},
                {"asset": "BTC", "walletBalance": "0.10", "maintMargin": "0"},
                {"asset": "ETH", "walletBalance": "0", "maintMargin": "0"},
            ],
        }


def test_binance_account_adapter_loads_domain_account_snapshot():
    client = FakeBinanceAccountClient()
    adapter = BinanceAccountAdapter(client)

    snapshot = adapter.load_account_snapshot()

    assert isinstance(adapter, AccountPort)
    assert client.calls == 1
    assert snapshot == AccountSnapshot(
        balances=(
            AssetBalance("USDT", free=Decimal("1000.25"), locked=Decimal("12.5")),
            AssetBalance("BTC", free=Decimal("0.10"), locked=Decimal("0")),
        ),
        total_equity=Decimal("1200.50"),
    )


class FakeBinanceSpotAccountClient:
    def __init__(self) -> None:
        self.calls = 0

    def get_account(self):
        self.calls += 1
        return {
            "balances": [
                {"asset": "USDT", "free": "1000.25", "locked": "12.5"},
                {"asset": "BTC", "free": "0.10", "locked": "0"},
                {"asset": "ETH", "free": "0", "locked": "0"},
            ],
        }


def test_binance_account_adapter_loads_spot_account_snapshot_when_futures_is_unavailable():
    client = FakeBinanceSpotAccountClient()
    adapter = BinanceAccountAdapter(client)

    snapshot = adapter.load_account_snapshot()

    assert client.calls == 1
    assert snapshot == AccountSnapshot(
        balances=(
            AssetBalance("USDT", free=Decimal("1000.25"), locked=Decimal("12.5")),
            AssetBalance("BTC", free=Decimal("0.10"), locked=Decimal("0")),
        ),
        total_equity=Decimal("1012.85"),
    )
