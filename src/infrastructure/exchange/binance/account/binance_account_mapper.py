from decimal import Decimal
from typing import Mapping

from src.domain.ports import AccountSnapshot, AssetBalance


def map_binance_account_to_snapshot(payload: Mapping[str, object]) -> AccountSnapshot:
    balances = tuple(
        AssetBalance(
            asset=str(asset["asset"]),
            free=Decimal(str(asset["walletBalance"])),
            locked=Decimal(str(asset.get("maintMargin", "0"))),
        )
        for asset in payload.get("assets", ())
        if _has_balance(asset)
    )
    return AccountSnapshot(
        balances=balances,
        total_equity=Decimal(str(payload["totalWalletBalance"])),
    )


def _has_balance(asset: Mapping[str, object]) -> bool:
    free = Decimal(str(asset["walletBalance"]))
    locked = Decimal(str(asset.get("maintMargin", "0")))
    return free > Decimal("0") or locked > Decimal("0")
