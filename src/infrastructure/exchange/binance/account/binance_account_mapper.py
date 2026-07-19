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
            free=_decimal_field(asset, "availableBalance", "walletBalance"),
            locked=_futures_locked_margin(asset),
        )
        for asset in payload.get("assets", ())
        if _has_balance(asset)
    )
    return AccountSnapshot(
        balances=balances,
        total_equity=_decimal_field(payload, "totalMarginBalance", "totalWalletBalance"),
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
    free = _decimal_field(asset, "availableBalance", "walletBalance")
    locked = _futures_locked_margin(asset)
    return free > Decimal("0") or locked > Decimal("0")


def _has_spot_balance(balance: Mapping[str, object]) -> bool:
    free = Decimal(str(balance["free"]))
    locked = Decimal(str(balance["locked"]))
    return free > Decimal("0") or locked > Decimal("0")


def _decimal_field(payload: Mapping[str, object], *names: str) -> Decimal:
    for name in names:
        if name in payload:
            return Decimal(str(payload[name]))
    return Decimal("0")


def _futures_locked_margin(asset: Mapping[str, object]) -> Decimal:
    if "initialMargin" in asset:
        return Decimal(str(asset["initialMargin"]))
    open_order_margin = Decimal(str(asset.get("openOrderInitialMargin", "0")))
    position_margin = Decimal(str(asset.get("positionInitialMargin", "0")))
    if open_order_margin or position_margin:
        return open_order_margin + position_margin
    return Decimal(str(asset.get("maintMargin", "0")))
