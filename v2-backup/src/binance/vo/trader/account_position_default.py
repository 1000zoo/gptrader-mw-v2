from typing import Optional

from src.common.model.base import Vo


class DefaultAccountPositionVo(Vo):
    symbol: Optional[str] = None

    position_amt: Optional[float] = None
    entry_price: Optional[float] = None
    break_even_price: Optional[float] = None
    mark_price: Optional[float] = None
    unrealized_profit: Optional[float] = None
    liquidation_price: Optional[float] = None
    leverage: Optional[int] = None

    max_notional_value: Optional[float] = None
    max_notional: Optional[float] = None
    notional: Optional[float] = None
    bid_notional: Optional[float] = None
    ask_notional: Optional[float] = None

    margin_type: Optional[str] = None
    isolated: Optional[bool] = None
    isolated_margin: Optional[float] = None
    isolated_wallet: Optional[float] = None
    is_auto_add_margin: Optional[bool] = None
    position_side: Optional[str] = None

    initial_margin: Optional[float] = None
    maint_margin: Optional[float] = None
    position_initial_margin: Optional[float] = None
    open_order_initial_margin: Optional[float] = None

    update_time: Optional[int] = None
    adl: Optional[int] = None

    class Config:
        from_attributes = True
        extra = "ignore"
