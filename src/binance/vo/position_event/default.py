from typing import Optional

from src.common.model.base import Vo


class DefaultPositionEventVo(Vo):
    id: Optional[int] = None

    reg_ymd: Optional[str] = None
    batch_id: Optional[str] = None
    symbol_id: Optional[str] = None

    event_type: Optional[str] = None
    side: Optional[str] = None
    qty: Optional[float] = None
    price: Optional[float] = None
    order_id: Optional[str] = None
    position_side: Optional[str] = None
    order_type: Optional[str] = None
    execution_type: Optional[str] = None
    pnl: Optional[float] = None

    class Config:
        from_attributes = True
        extra = "ignore"
