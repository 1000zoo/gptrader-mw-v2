from decimal import Decimal
from typing import Protocol

import pytest

from src.domain.ports import AccountPort, AccountSnapshot, AssetBalance


class StaticAccountPort:
    def __init__(self, snapshot: AccountSnapshot) -> None:
        self.snapshot = snapshot

    def load_account_snapshot(self) -> AccountSnapshot:
        return self.snapshot


def test_account_port_is_protocol_contract():
    assert issubclass(AccountPort, Protocol)


def test_asset_balance_requires_non_negative_values():
    with pytest.raises(ValueError, match="free must be greater than or equal to zero"):
        AssetBalance(asset="USDT", free=Decimal("-1"), locked=Decimal("0"))


def test_account_snapshot_exposes_total_equity_and_asset_lookup():
    usdt = AssetBalance(asset=" usdt ", free=Decimal("100"), locked=Decimal("5"))
    btc = AssetBalance(asset="BTC", free=Decimal("0.25"), locked=Decimal("0"))
    snapshot = AccountSnapshot(balances=(usdt, btc), total_equity=Decimal("105"))
    port = StaticAccountPort(snapshot)

    loaded = port.load_account_snapshot()

    assert isinstance(port, AccountPort)
    assert loaded.balance_for("usdt") == usdt
    assert loaded.balance_for("ETH") is None
    assert usdt.asset == "USDT"
