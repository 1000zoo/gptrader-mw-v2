from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class AssetBalance:
    asset: str
    free: Decimal
    locked: Decimal

    def __post_init__(self) -> None:
        asset = self.asset.strip().upper()
        if not asset:
            raise ValueError("asset is required")
        if self.free < Decimal("0"):
            raise ValueError("free must be greater than or equal to zero")
        if self.locked < Decimal("0"):
            raise ValueError("locked must be greater than or equal to zero")

        object.__setattr__(self, "asset", asset)

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


@dataclass(frozen=True)
class AccountSnapshot:
    balances: Sequence[AssetBalance]
    total_equity: Decimal

    def __post_init__(self) -> None:
        balances = tuple(self.balances)
        if self.total_equity < Decimal("0"):
            raise ValueError("total_equity must be greater than or equal to zero")

        assets = [balance.asset for balance in balances]
        if len(assets) != len(set(assets)):
            raise ValueError("balances must not contain duplicate assets")

        object.__setattr__(self, "balances", balances)

    def balance_for(self, asset: str) -> AssetBalance | None:
        normalized_asset = asset.strip().upper()
        for balance in self.balances:
            if balance.asset == normalized_asset:
                return balance
        return None


@runtime_checkable
class AccountPort(Protocol):
    def load_account_snapshot(self) -> AccountSnapshot:
        ...
