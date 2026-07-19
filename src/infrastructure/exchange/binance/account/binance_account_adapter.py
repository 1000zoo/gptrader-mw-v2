from typing import Mapping, cast

from src.domain.ports import AccountPort, AccountSnapshot
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.binance_rest import request_json
from src.infrastructure.exchange.binance.account.binance_account_mapper import (
    map_binance_account_to_snapshot,
)


class BinanceAccountAdapter(AccountPort):
    def __init__(self, config: BinanceConfig | None = None) -> None:
        self._config = config or BinanceConfig.from_env()

    def load_account_snapshot(self) -> AccountSnapshot:
        return map_binance_account_to_snapshot(load_account_api(self._config))


def load_account_api(config: BinanceConfig) -> Mapping[str, object]:
    return cast(
        Mapping[str, object],
        request_json(config, "GET", "/fapi/v2/account", signed=True),
    )
