from typing import Any, Optional

from src.binance.api.trader.account_api import AccountApi
from src.binance.vo.trader.account_position_default import DefaultAccountPositionVo
from src.common.exception.external_api_error import ExternalApiError


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        low = value.lower()
        if low in {"true", "1", "y", "yes"}:
            return True
        if low in {"false", "0", "n", "no"}:
            return False
    return None


def _to_position_vo(position: dict[str, Any]) -> DefaultAccountPositionVo:
    return DefaultAccountPositionVo(
        symbol=position.get("symbol"),
        position_amt=_to_float(position.get("positionAmt")),
        entry_price=_to_float(position.get("entryPrice")),
        break_even_price=_to_float(position.get("breakEvenPrice")),
        mark_price=_to_float(position.get("markPrice")),
        unrealized_profit=_to_float(position.get("unRealizedProfit") or position.get("unrealizedProfit")),
        liquidation_price=_to_float(position.get("liquidationPrice")),
        leverage=_to_int(position.get("leverage")),
        max_notional_value=_to_float(position.get("maxNotionalValue")),
        max_notional=_to_float(position.get("maxNotional")),
        margin_type=position.get("marginType"),
        isolated=_to_bool(position.get("isolated")),
        isolated_margin=_to_float(position.get("isolatedMargin")),
        is_auto_add_margin=_to_bool(position.get("isAutoAddMargin")),
        position_side=position.get("positionSide"),
        notional=_to_float(position.get("notional")),
        isolated_wallet=_to_float(position.get("isolatedWallet")),
        update_time=_to_int(position.get("updateTime")),
        bid_notional=_to_float(position.get("bidNotional")),
        ask_notional=_to_float(position.get("askNotional")),
        initial_margin=_to_float(position.get("initialMargin")),
        maint_margin=_to_float(position.get("maintMargin")),
        position_initial_margin=_to_float(position.get("positionInitialMargin")),
        open_order_initial_margin=_to_float(position.get("openOrderInitialMargin")),
        adl=_to_int(position.get("adl")),
    )


class AccountService:
    def __init__(self):
        self.api = AccountApi()


    def has_position(self):
        try:
            return len(self.get_positions()) > 0
        except ExternalApiError as e:
            raise ExternalApiError("Failed to determine if account has positions.") from e

    def get_usdt_balance(self) -> float:
        try:
            return float(self.api.get_usdt_balance())
        except ExternalApiError as e:
            raise ExternalApiError("Failed to fetch USDT balance.") from e

    def get_positions(self) -> list[DefaultAccountPositionVo]:
        try:
            return [_to_position_vo(position) for position in self.api.get_current_positions()]
        except ExternalApiError as e:
            raise ExternalApiError("Failed to fetch account positions.") from e
