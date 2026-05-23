from typing import Any

from src.domain.ports import AccountPort, AccountSnapshot
from src.infrastructure.exchange.binance.account.binance_account_mapper import (
    map_binance_account_to_snapshot,
)


class BinanceAccountAdapter(AccountPort):
    def __init__(self, client: Any) -> None:
        self._client = client

    def load_account_snapshot(self) -> AccountSnapshot:
        return map_binance_account_to_snapshot(self._client.get_account())
