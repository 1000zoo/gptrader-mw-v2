from decimal import Decimal
from typing import Mapping

from src.domain.ports import AccountSnapshot, AssetBalance


def map_binance_account_to_snapshot(payload: Mapping[str, object]) -> AccountSnapshot:
    if "balances" in payload:
        return _map_spot_account_to_snapshot(payload)
    return _map_futures_account_to_snapshot(payload)


def _map_futures_account_to_snapshot(payload: Mapping[str, object]) -> AccountSnapshot:
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


def _map_spot_account_to_snapshot(payload: Mapping[str, object]) -> AccountSnapshot:
    balances = tuple(
        AssetBalance(
            asset=str(balance["asset"]),
            free=Decimal(str(balance["free"])),
            locked=Decimal(str(balance["locked"])),
        )
        for balance in payload.get("balances", ())
        if _has_spot_balance(balance)
    )
    return AccountSnapshot(
        balances=balances,
        total_equity=sum(
            (balance.total for balance in balances),
            Decimal("0"),
        ),
    )


def _has_balance(asset: Mapping[str, object]) -> bool:
    free = Decimal(str(asset["walletBalance"]))
    locked = Decimal(str(asset.get("maintMargin", "0")))
    return free > Decimal("0") or locked > Decimal("0")


def _has_spot_balance(balance: Mapping[str, object]) -> bool:
    free = Decimal(str(balance["free"]))
    locked = Decimal(str(balance["locked"]))
    return free > Decimal("0") or locked > Decimal("0")
